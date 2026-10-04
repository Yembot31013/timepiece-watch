from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

POWER_SUPPLY_ROOT = Path("/sys/class/power_supply")
_CHARGING_STATUSES = frozenset({"charging", "full"})


@dataclass(frozen=True)
class BatteryReading:
    name: str
    percent: int
    status: str

    @property
    def is_charging(self) -> bool:
        return self.status.lower() in _CHARGING_STATUSES


@dataclass(frozen=True)
class BatteryPolicy:
    enabled: bool = True
    low_percent: int = 15
    recover_percent: int = 25
    reminder_seconds: float = 1800.0


@dataclass(frozen=True)
class BatteryAlertState:
    alerted: bool = False
    last_alert_at: float | None = None


def read_battery(root: Path = POWER_SUPPLY_ROOT) -> BatteryReading | None:
    if not root.is_dir():
        return None
    readings: list[BatteryReading] = []
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return None
    for entry in entries:
        reading = _read_one(entry)
        if reading is not None:
            readings.append(reading)
    if not readings:
        return None
    return min(readings, key=lambda item: item.percent)


def evaluate_battery(
    reading: BatteryReading | None,
    state: BatteryAlertState,
    now: float,
    policy: BatteryPolicy,
) -> tuple[str | None, BatteryAlertState]:
    if not policy.enabled or reading is None:
        return None, state
    if reading.is_charging or reading.percent > policy.recover_percent:
        return None, BatteryAlertState()
    if reading.percent > policy.low_percent:
        return None, state
    if not state.alerted:
        return format_battery_alert(reading, reminder=False), BatteryAlertState(
            alerted=True,
            last_alert_at=now,
        )
    if state.last_alert_at is not None and now - state.last_alert_at >= policy.reminder_seconds:
        return format_battery_alert(reading, reminder=True), BatteryAlertState(
            alerted=True,
            last_alert_at=now,
        )
    return None, state


def format_battery_alert(reading: BatteryReading, reminder: bool) -> str:
    title = "Battery still low" if reminder else "Low battery"
    status = reading.status.lower()
    return "\n".join(
        [
            f"🔋 <b>{title}</b>",
            f"{reading.percent}% left and {status}.",
            "",
            "Plug the laptop in so Timepiece watch stays online.",
        ]
    )


def check_battery(
    state: BatteryAlertState,
    policy: BatteryPolicy,
    now: float,
    reader: Callable[[], BatteryReading | None] = read_battery,
) -> tuple[str | None, BatteryAlertState]:
    return evaluate_battery(reader(), state, now, policy)


def _read_one(entry: Path) -> BatteryReading | None:
    if not _is_battery(entry):
        return None
    percent = _read_percent(entry / "capacity")
    status = _read_text(entry / "status")
    if percent is None or status is None:
        return None
    return BatteryReading(name=entry.name, percent=percent, status=status)


def _is_battery(entry: Path) -> bool:
    kind = _read_text(entry / "type")
    return kind is not None and kind.lower() == "battery"


def _read_percent(path: Path) -> int | None:
    raw = _read_text(path)
    if raw is None:
        return None
    try:
        percent = int(raw)
    except ValueError:
        return None
    if percent < 0 or percent > 100:
        return None
    return percent


def _read_text(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None
