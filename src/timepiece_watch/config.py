from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from pathlib import Path

from timepiece_watch.battery import BatteryPolicy
from timepiece_watch.changes import DEFAULT_SOLD_FAST_SECONDS
from timepiece_watch.client import TIMEPIECE_SALES_ACCOUNT_ID
from timepiece_watch.telegram import TelegramSettings

DEFAULT_ENV_PATH = Path(".env")


def load_env_file(
    path: Path = DEFAULT_ENV_PATH,
    environ: MutableMapping[str, str] | None = None,
) -> None:
    target = os.environ if environ is None else environ
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in target:
            target[key] = value


def telegram_settings_from_env(environ: Mapping[str, str] | None = None) -> TelegramSettings | None:
    source = os.environ if environ is None else environ
    token = (source.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (source.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return None
    return TelegramSettings(bot_token=token, chat_id=chat_id)


def sold_fast_seconds_from_env(environ: Mapping[str, str] | None = None) -> float:
    source = os.environ if environ is None else environ
    raw = (source.get("WATCH_SOLD_FAST_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_SOLD_FAST_SECONDS
    try:
        parsed = float(raw)
    except ValueError:
        return DEFAULT_SOLD_FAST_SECONDS
    if parsed < 0:
        return DEFAULT_SOLD_FAST_SECONDS
    return parsed


def organiser_ids_from_env(environ: Mapping[str, str] | None = None) -> frozenset[int]:
    source = os.environ if environ is None else environ
    extras = _int_set(source.get("WATCH_ORGANISER_IDS"))
    return frozenset({TIMEPIECE_SALES_ACCOUNT_ID}) | extras


def battery_policy_from_env(environ: Mapping[str, str] | None = None) -> BatteryPolicy:
    source = os.environ if environ is None else environ
    defaults = BatteryPolicy()
    low_percent = _percent(source.get("BATTERY_LOW_PERCENT"), defaults.low_percent)
    recover_percent = max(
        low_percent,
        _percent(source.get("BATTERY_RECOVER_PERCENT"), defaults.recover_percent),
    )
    return BatteryPolicy(
        enabled=_truthy(source.get("BATTERY_ALERT"), default=True),
        low_percent=low_percent,
        recover_percent=recover_percent,
        reminder_seconds=float(
            _positive_int(
                source.get("BATTERY_REMINDER_SECONDS"),
                int(defaults.reminder_seconds),
            )
        ),
    )


def _truthy(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _positive_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value.strip())
    except ValueError:
        return default
    if parsed <= 0:
        return default
    return parsed


def _percent(value: str | None, default: int) -> int:
    return min(_positive_int(value, default), 100)


def _int_set(value: str | None) -> frozenset[int]:
    if value is None or not value.strip():
        return frozenset()
    parsed: set[int] = set()
    for part in value.replace(",", " ").split():
        try:
            number = int(part)
        except ValueError:
            continue
        if number > 0:
            parsed.add(number)
    return frozenset(parsed)
