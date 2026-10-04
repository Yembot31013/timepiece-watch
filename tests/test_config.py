from pathlib import Path

from timepiece_watch.client import TIMEPIECE_SALES_ACCOUNT_ID
from timepiece_watch.config import (
    battery_policy_from_env,
    load_env_file,
    organiser_ids_from_env,
    sold_fast_seconds_from_env,
    telegram_settings_from_env,
)


def test_load_env_file_parses_values_without_overriding(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=from-file\nTELEGRAM_CHAT_ID='111'\n# comment\nEXISTING=file\n",
        encoding="utf-8",
    )
    environ = {"EXISTING": "already"}

    load_env_file(env_file, environ)

    assert environ["TELEGRAM_BOT_TOKEN"] == "from-file"
    assert environ["TELEGRAM_CHAT_ID"] == "111"
    assert environ["EXISTING"] == "already"


def test_telegram_settings_require_both_values() -> None:
    assert telegram_settings_from_env({}) is None
    assert telegram_settings_from_env({"TELEGRAM_BOT_TOKEN": "123:abc"}) is None

    settings = telegram_settings_from_env(
        {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "99"}
    )
    assert settings is not None
    assert settings.bot_token == "123:abc"
    assert settings.chat_id == "99"


def test_missing_env_file_is_ignored(tmp_path: Path) -> None:
    environ: dict[str, str] = {}
    load_env_file(tmp_path / "missing.env", environ)
    assert environ == {}


def test_sold_fast_seconds_defaults_and_can_be_disabled() -> None:
    assert sold_fast_seconds_from_env({}) == 600.0
    assert sold_fast_seconds_from_env({"WATCH_SOLD_FAST_SECONDS": "180"}) == 180.0
    assert sold_fast_seconds_from_env({"WATCH_SOLD_FAST_SECONDS": "0"}) == 0.0
    assert sold_fast_seconds_from_env({"WATCH_SOLD_FAST_SECONDS": "nope"}) == 600.0
    assert sold_fast_seconds_from_env({"WATCH_SOLD_FAST_SECONDS": "-10"}) == 600.0


def test_battery_policy_uses_defaults_and_parses_overrides() -> None:
    defaults = battery_policy_from_env({})
    assert defaults.enabled is True
    assert defaults.low_percent == 15
    assert defaults.recover_percent == 25
    assert defaults.reminder_seconds == 1800

    custom = battery_policy_from_env(
        {
            "BATTERY_ALERT": "0",
            "BATTERY_LOW_PERCENT": "20",
            "BATTERY_RECOVER_PERCENT": "35",
            "BATTERY_REMINDER_SECONDS": "600",
        }
    )
    assert custom.enabled is False
    assert custom.low_percent == 20
    assert custom.recover_percent == 35
    assert custom.reminder_seconds == 600


def test_battery_policy_keeps_recover_at_or_above_low() -> None:
    policy = battery_policy_from_env({"BATTERY_LOW_PERCENT": "40", "BATTERY_RECOVER_PERCENT": "20"})
    assert policy.low_percent == 40
    assert policy.recover_percent == 40


def test_organiser_ids_always_include_timepiece_and_parse_extras() -> None:
    assert organiser_ids_from_env({}) == frozenset({TIMEPIECE_SALES_ACCOUNT_ID})
    assert organiser_ids_from_env({"WATCH_ORGANISER_IDS": "509037417, 5486166"}) == frozenset(
        {TIMEPIECE_SALES_ACCOUNT_ID, 509037417}
    )
    assert organiser_ids_from_env({"WATCH_ORGANISER_IDS": "nope,12,-3"}) == frozenset(
        {TIMEPIECE_SALES_ACCOUNT_ID, 12}
    )


def test_battery_policy_ignores_invalid_numbers() -> None:
    policy = battery_policy_from_env(
        {
            "BATTERY_LOW_PERCENT": "nope",
            "BATTERY_RECOVER_PERCENT": "-1",
            "BATTERY_REMINDER_SECONDS": "0",
        }
    )
    defaults = battery_policy_from_env({})
    assert policy.low_percent == defaults.low_percent
    assert policy.recover_percent == defaults.recover_percent
    assert policy.reminder_seconds == defaults.reminder_seconds
