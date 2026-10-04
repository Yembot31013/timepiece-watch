from timepiece_watch.battery import BatteryAlertState
from timepiece_watch.delivery import (
    NotifyResult,
    commit_battery,
    commit_events,
    notify,
    resolve_telegram_settings,
)
from timepiece_watch.telegram import TelegramError, TelegramSettings


def test_resolve_telegram_prefers_stored_chat_id() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="-111")
    resolved = resolve_telegram_settings(settings, "-100222")
    assert resolved == TelegramSettings(bot_token="123:abc", chat_id="-100222")
    assert resolve_telegram_settings(None, "-100222") is None
    assert resolve_telegram_settings(settings, None) == settings


def test_commit_events_holds_previous_when_telegram_send_fails() -> None:
    previous = {1: "old"}
    current = {1: "new"}
    assert commit_events(previous, current, telegram_enabled=True, delivered=False) == previous
    assert commit_events(previous, current, telegram_enabled=True, delivered=True) == current
    assert commit_events(previous, current, telegram_enabled=False, delivered=False) == current


def test_partial_delivery_failure_retries_the_whole_snapshot() -> None:
    previous = {1: "listed"}
    current = {1: "on_sale"}
    first_message_sent = True
    second_message_failed = False
    delivered = first_message_sent and second_message_failed
    assert commit_events(previous, current, telegram_enabled=True, delivered=delivered) == previous


def test_commit_battery_holds_latch_when_telegram_send_fails() -> None:
    previous = BatteryAlertState()
    alerted = BatteryAlertState(alerted=True, last_alert_at=10.0)
    assert commit_battery(previous, alerted, telegram_enabled=True, delivered=False) == previous
    assert commit_battery(previous, alerted, telegram_enabled=True, delivered=True) == alerted
    assert commit_battery(previous, alerted, telegram_enabled=False, delivered=False) == alerted


def test_notify_without_telegram_is_delivered() -> None:
    result = notify(None, "hello")
    assert result == NotifyResult(delivered=True, settings=None)


def test_notify_returns_error_and_keeps_settings() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="-111")

    def fail(_settings: TelegramSettings, _text: str) -> str:
        raise TelegramError("Telegram returned HTTP 400: chat not found")

    result = notify(settings, "ON SALE", send=fail)
    assert result.delivered is False
    assert result.settings == settings
    assert result.error is not None
    assert "chat not found" in result.error


def test_notify_tracks_migrated_chat_id() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="-111")

    result = notify(settings, "ON SALE", send=lambda _settings, _text: "-100222")
    assert result.delivered is True
    assert result.migrated is True
    assert result.settings == TelegramSettings(bot_token="123:abc", chat_id="-100222")
