from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

from timepiece_watch.battery import BatteryAlertState, BatteryPolicy, check_battery
from timepiece_watch.client import FixrClient, FixrError, FixrHttpError
from timepiece_watch.config import (
    battery_policy_from_env,
    load_env_file,
    organiser_ids_from_env,
    sold_fast_seconds_from_env,
    telegram_settings_from_env,
)
from timepiece_watch.delivery import commit_battery, commit_events, notify, resolve_telegram_settings
from timepiece_watch.notifier import format_alert_messages, format_status
from timepiece_watch.rate_limit import RatePolicy, next_sleep
from timepiece_watch.state import (
    DEFAULT_STATE_PATH,
    load_battery_state,
    load_state,
    load_telegram_chat_id,
    save_state,
)
from timepiece_watch.telegram import TelegramSettings
from timepiece_watch.watcher import poll_once


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="timepiece-watch",
        description="Watch Timepiece FIXR listings for coming-soon and on-sale tickets.",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help="Path to the local snapshot file (default: .state.json)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="Print current Timepiece ticket status once")
    watch = subparsers.add_parser("watch", help="Poll until interrupted and print changes")
    watch.add_argument("--once", action="store_true", help="Run a single watch cycle and exit")
    args = parser.parse_args(argv)

    load_env_file()
    client = FixrClient(timeout_seconds=30.0, min_interval_seconds=0.5)
    organiser_ids = organiser_ids_from_env()
    sold_fast_seconds = sold_fast_seconds_from_env()
    if args.command == "check":
        return _run_check(client, organiser_ids, sold_fast_seconds)
    return _run_watch(
        client,
        state_path=args.state,
        once=args.once,
        organiser_ids=organiser_ids,
        sold_fast_seconds=sold_fast_seconds,
    )


def _run_check(client: FixrClient, organiser_ids: frozenset[int], sold_fast_seconds: float) -> int:
    try:
        result = poll_once(
            client,
            previous={},
            organiser_ids=organiser_ids,
            sold_fast_seconds=sold_fast_seconds,
        )
    except (FixrError, ValueError) as error:
        print(f"Could not read Timepiece listings: {error}", file=sys.stderr)
        return 1
    print(format_status(tuple(result.events.values())))
    return 0


def _run_watch(
    client: FixrClient,
    state_path: Path,
    once: bool,
    organiser_ids: frozenset[int],
    sold_fast_seconds: float,
) -> int:
    previous = load_state(state_path)
    telegram = resolve_telegram_settings(
        telegram_settings_from_env(),
        load_telegram_chat_id(state_path),
    )
    battery_policy = battery_policy_from_env()
    battery_state = load_battery_state(state_path)
    _announce_telegram(telegram)
    _announce_organisers(organiser_ids)
    consecutive_errors = 0
    last_fetched_at: dict[int, float] = {}
    while True:
        started_chat_id = _chat_id(telegram)
        candidate_battery, telegram, battery_delivered = _notify_battery(
            telegram,
            battery_state,
            battery_policy,
        )
        next_battery = commit_battery(
            battery_state,
            candidate_battery,
            telegram_enabled=telegram is not None,
            delivered=battery_delivered,
        )
        if next_battery != battery_state or _chat_id(telegram) != started_chat_id:
            save_state(state_path, previous, next_battery, _chat_id(telegram))
        battery_state = next_battery
        try:
            result = poll_once(
                client,
                previous,
                last_fetched_at=last_fetched_at,
                organiser_ids=organiser_ids,
                sold_fast_seconds=sold_fast_seconds,
            )
        except FixrHttpError as error:
            consecutive_errors += 1
            sleep_seconds = _error_sleep(consecutive_errors, error.retry_after)
            print(
                f"FIXR request failed ({error}). Sleeping {sleep_seconds:.0f}s.",
                file=sys.stderr,
            )
            if once:
                return 1
            time.sleep(sleep_seconds)
            continue
        except (FixrError, ValueError) as error:
            consecutive_errors += 1
            sleep_seconds = _error_sleep(consecutive_errors, None)
            print(f"Watch cycle failed: {error}. Sleeping {sleep_seconds:.0f}s.", file=sys.stderr)
            if once:
                return 1
            time.sleep(sleep_seconds)
            continue

        consecutive_errors = 0
        last_fetched_at = result.last_fetched_at
        if not previous:
            print(format_status(tuple(result.events.values())))
        delivered = True
        for alert in result.alerts:
            messages = format_alert_messages(alert)
            for index, text in enumerate(messages):
                print(text)
                print()
                sent, telegram = _deliver(telegram, text)
                delivered = delivered and sent
                if telegram is not None and index < len(messages) - 1:
                    time.sleep(0.35)
        if previous and not result.alerts:
            print(
                f"No change. Next poll in {_display_sleep(result.sleep_seconds, result.sleep_reason)} "
                f"({result.sleep_reason})."
            )
        if result.alerts and not delivered:
            print(
                "Telegram delivery failed. Keeping previous snapshot so ticket alerts retry.",
                file=sys.stderr,
            )

        previous = commit_events(
            previous,
            result.events,
            telegram_enabled=telegram is not None,
            delivered=delivered,
        )
        save_state(state_path, previous, battery_state, _chat_id(telegram))
        if once:
            return 0
        time.sleep(_jitter(result.sleep_seconds))


def _announce_organisers(organiser_ids: frozenset[int]) -> None:
    listed = ", ".join(str(organiser_id) for organiser_id in sorted(organiser_ids))
    print(f"Watching organisers: {listed}", file=sys.stderr)


def _announce_telegram(telegram: TelegramSettings | None) -> None:
    if telegram is None:
        print(
            "Telegram alerts: off. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable.",
            file=sys.stderr,
        )
        return
    print(f"Telegram alerts: on (chat {telegram.chat_id})", file=sys.stderr)


def _notify_battery(
    telegram: TelegramSettings | None,
    state: BatteryAlertState,
    policy: BatteryPolicy,
) -> tuple[BatteryAlertState, TelegramSettings | None, bool]:
    message, next_state = check_battery(state, policy, time.time())
    if message is None:
        return next_state, telegram, True
    print(message)
    print()
    delivered, telegram = _deliver(telegram, message)
    return next_state, telegram, delivered


def _deliver(
    telegram: TelegramSettings | None,
    text: str,
) -> tuple[bool, TelegramSettings | None]:
    result = notify(telegram, text)
    if result.migrated and result.settings is not None:
        print(
            f"Telegram chat migrated to {result.settings.chat_id}. "
            "Update TELEGRAM_CHAT_ID in .env.",
            file=sys.stderr,
        )
    if result.error:
        print(f"Telegram send failed: {result.error}", file=sys.stderr)
        return False, result.settings
    return True, result.settings


def _chat_id(telegram: TelegramSettings | None) -> str | None:
    if telegram is None:
        return None
    return telegram.chat_id


def _error_sleep(consecutive_errors: int, retry_after: float | None) -> float:
    decision = next_sleep(
        (),
        consecutive_errors=consecutive_errors,
        retry_after=retry_after,
        jitter=_signed_jitter,
    )
    return decision.sleep_seconds


def _jitter(seconds: float) -> float:
    return max(1.0, seconds + _signed_jitter(seconds))


def _signed_jitter(seconds: float) -> float:
    return seconds * RatePolicy().jitter_ratio * random.uniform(-1.0, 1.0)


def _display_sleep(seconds: float, reason: str) -> str:
    del reason
    return f"{seconds:.0f}s"


if __name__ == "__main__":
    raise SystemExit(main())
