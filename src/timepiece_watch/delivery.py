from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from timepiece_watch.battery import BatteryAlertState
from timepiece_watch.models import EventSnapshot
from timepiece_watch.telegram import TelegramError, TelegramSettings, send_message


@dataclass(frozen=True)
class NotifyResult:
    delivered: bool
    settings: TelegramSettings | None
    error: str | None = None
    migrated: bool = False


def resolve_telegram_settings(
    settings: TelegramSettings | None,
    stored_chat_id: str | None,
) -> TelegramSettings | None:
    if settings is None:
        return None
    chat_id = (stored_chat_id or "").strip()
    if not chat_id:
        return settings
    return TelegramSettings(bot_token=settings.bot_token, chat_id=chat_id)


def notify(
    settings: TelegramSettings | None,
    text: str,
    send: Callable[[TelegramSettings, str], str] = send_message,
) -> NotifyResult:
    if settings is None:
        return NotifyResult(delivered=True, settings=None)
    try:
        chat_id = send(settings, text)
    except TelegramError as error:
        return NotifyResult(delivered=False, settings=settings, error=str(error))
    if not chat_id or chat_id == settings.chat_id:
        return NotifyResult(delivered=True, settings=settings)
    return NotifyResult(
        delivered=True,
        settings=TelegramSettings(bot_token=settings.bot_token, chat_id=chat_id),
        migrated=True,
    )


def commit_events(
    previous: Mapping[int, EventSnapshot],
    current: Mapping[int, EventSnapshot],
    telegram_enabled: bool,
    delivered: bool,
) -> dict[int, EventSnapshot]:
    # Hold the whole snapshot if any send failed. That can duplicate a
    # message that already went out, which is better than dropping ON SALE.
    if telegram_enabled and not delivered:
        return dict(previous)
    return dict(current)


def commit_battery(
    previous: BatteryAlertState,
    current: BatteryAlertState,
    telegram_enabled: bool,
    delivered: bool,
) -> BatteryAlertState:
    if telegram_enabled and not delivered:
        return previous
    return current
