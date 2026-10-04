from pathlib import Path
from unittest.mock import patch

from timepiece_watch.battery import (
    BatteryAlertState,
    BatteryPolicy,
    BatteryReading,
    check_battery,
    evaluate_battery,
    format_battery_alert,
    read_battery,
)


def _write_supply(root: Path, name: str, *, kind: str, capacity: str | None, status: str | None) -> None:
    directory = root / name
    directory.mkdir()
    (directory / "type").write_text(f"{kind}\n", encoding="utf-8")
    if capacity is not None:
        (directory / "capacity").write_text(f"{capacity}\n", encoding="utf-8")
    if status is not None:
        (directory / "status").write_text(f"{status}\n", encoding="utf-8")


def test_read_battery_returns_none_when_sysfs_missing(tmp_path: Path) -> None:
    assert read_battery(tmp_path / "missing") is None


def test_read_battery_ignores_mains_and_reads_lowest_battery(tmp_path: Path) -> None:
    _write_supply(tmp_path, "AC", kind="Mains", capacity=None, status="Online")
    _write_supply(tmp_path, "BAT1", kind="Battery", capacity="41", status="Full")
    _write_supply(tmp_path, "BAT0", kind="Battery", capacity="12", status="Discharging")

    reading = read_battery(tmp_path)

    assert reading == BatteryReading(name="BAT0", percent=12, status="Discharging")


def test_read_battery_skips_unreadable_or_invalid_capacity(tmp_path: Path) -> None:
    _write_supply(tmp_path, "BAT0", kind="Battery", capacity="nope", status="Discharging")
    _write_supply(tmp_path, "HID", kind="Battery", capacity=None, status="Discharging")
    _write_supply(tmp_path, "BAT2", kind="Battery", capacity="140", status="Discharging")

    assert read_battery(tmp_path) is None


def test_read_battery_returns_none_when_listing_fails(tmp_path: Path) -> None:
    with patch.object(Path, "iterdir", side_effect=OSError("permission denied")):
        assert read_battery(tmp_path) is None


def test_check_battery_reads_then_evaluates() -> None:
    reading = BatteryReading(name="BAT0", percent=9, status="Discharging")

    message, state = check_battery(
        BatteryAlertState(),
        BatteryPolicy(low_percent=15, recover_percent=25, reminder_seconds=1800),
        now=5.0,
        reader=lambda: reading,
    )

    assert message is not None
    assert "9%" in message
    assert state.alerted is True


def test_evaluate_alerts_once_when_discharging_at_or_below_threshold() -> None:
    policy = BatteryPolicy(low_percent=15, recover_percent=25, reminder_seconds=1800)
    reading = BatteryReading(name="BAT0", percent=12, status="Discharging")

    first, after_alert = evaluate_battery(reading, BatteryAlertState(), now=10.0, policy=policy)
    second, after_hold = evaluate_battery(reading, after_alert, now=20.0, policy=policy)

    assert first is not None
    assert "12%" in first
    assert "Low battery" in first
    assert second is None
    assert after_hold.alerted is True


def test_evaluate_does_not_alert_while_charging() -> None:
    policy = BatteryPolicy()
    reading = BatteryReading(name="BAT0", percent=8, status="Charging")

    message, state = evaluate_battery(reading, BatteryAlertState(), now=1.0, policy=policy)

    assert message is None
    assert state == BatteryAlertState()


def test_evaluate_resets_after_charge_so_later_drop_alerts_again() -> None:
    policy = BatteryPolicy(low_percent=15, recover_percent=25, reminder_seconds=1800)
    low = BatteryReading(name="BAT0", percent=10, status="Discharging")
    charging = BatteryReading(name="BAT0", percent=18, status="Charging")

    _, alerted = evaluate_battery(low, BatteryAlertState(), now=1.0, policy=policy)
    _, recovered = evaluate_battery(charging, alerted, now=2.0, policy=policy)
    again, _ = evaluate_battery(low, recovered, now=3.0, policy=policy)

    assert recovered == BatteryAlertState()
    assert again is not None


def test_evaluate_holds_between_low_and_recover_without_reset() -> None:
    policy = BatteryPolicy(low_percent=15, recover_percent=25, reminder_seconds=1800)
    low = BatteryReading(name="BAT0", percent=12, status="Discharging")
    mid = BatteryReading(name="BAT0", percent=20, status="Discharging")

    _, alerted = evaluate_battery(low, BatteryAlertState(), now=1.0, policy=policy)
    message, held = evaluate_battery(mid, alerted, now=2.0, policy=policy)

    assert message is None
    assert held.alerted is True


def test_evaluate_sends_reminder_after_interval_while_still_low() -> None:
    policy = BatteryPolicy(low_percent=15, recover_percent=25, reminder_seconds=1800)
    reading = BatteryReading(name="BAT0", percent=7, status="Discharging")

    _, alerted = evaluate_battery(reading, BatteryAlertState(), now=100.0, policy=policy)
    too_soon, _ = evaluate_battery(reading, alerted, now=1899.0, policy=policy)
    reminder, reminded = evaluate_battery(reading, alerted, now=1900.0, policy=policy)

    assert too_soon is None
    assert reminder is not None
    assert "still low" in reminder
    assert reminded.last_alert_at == 1900.0


def test_evaluate_is_silent_without_reading_or_when_disabled() -> None:
    policy = BatteryPolicy(enabled=False)
    reading = BatteryReading(name="BAT0", percent=5, status="Discharging")

    disabled, _ = evaluate_battery(reading, BatteryAlertState(), now=1.0, policy=policy)
    missing, _ = evaluate_battery(None, BatteryAlertState(), now=1.0, policy=BatteryPolicy())

    assert disabled is None
    assert missing is None


def test_format_battery_alert_asks_to_plug_in() -> None:
    text = format_battery_alert(
        BatteryReading(name="BAT0", percent=11, status="Discharging"),
        reminder=False,
    )

    assert "🔋" in text
    assert "<b>Low battery</b>" in text
    assert "11%" in text
    assert "Plug the laptop in" in text
