from __future__ import annotations

import json
import os
from pathlib import Path

from timepiece_watch.battery import BatteryAlertState
from timepiece_watch.models import EventSnapshot, TicketAvailability, TicketSnapshot

DEFAULT_STATE_PATH = Path(".state.json")


def load_state(path: Path) -> dict[int, EventSnapshot]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"State file is not valid JSON: {path}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError(f"State file has invalid structure: {path}")

    events: dict[int, EventSnapshot] = {}
    for item in payload["events"]:
        snapshot = _event_from_dict(item)
        events[snapshot.id] = snapshot
    return events


def load_telegram_chat_id(path: Path) -> str | None:
    payload = _existing_payload(path)
    return _chat_id_from_value(payload.get("telegram_chat_id"))


def load_battery_state(path: Path) -> BatteryAlertState:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return BatteryAlertState()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return BatteryAlertState()
    if not isinstance(payload, dict):
        return BatteryAlertState()
    return _battery_from_payload(payload.get("battery"))


def save_state(
    path: Path,
    events: dict[int, EventSnapshot],
    battery: BatteryAlertState | None = None,
    telegram_chat_id: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _existing_payload(path)
    if battery is None and isinstance(existing.get("battery"), dict):
        battery = _battery_from_payload(existing.get("battery"))
    if telegram_chat_id is None:
        telegram_chat_id = _chat_id_from_value(existing.get("telegram_chat_id"))
    payload: dict[str, object] = {
        "events": [_event_to_dict(event) for event in events.values()],
    }
    if battery is not None:
        payload["battery"] = {
            "alerted": battery.alerted,
            "last_alert_at": battery.last_alert_at,
        }
    if telegram_chat_id:
        payload["telegram_chat_id"] = telegram_chat_id
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # atomic on POSIX


def _event_to_dict(event: EventSnapshot) -> dict[str, object]:
    return {
        "id": event.id,
        "name": event.name,
        "share_url": event.share_url,
        "tickets_url": event.tickets_url,
        "label": event.label,
        "sold_out": event.sold_out,
        "organiser_id": event.organiser_id,
        "tickets": [
            {
                "id": ticket.id,
                "name": ticket.name,
                "availability": ticket.availability.value,
                "price": ticket.price,
                "on_sale_since": ticket.on_sale_since,
            }
            for ticket in event.tickets
        ],
    }


def _event_from_dict(payload: object) -> EventSnapshot:
    if not isinstance(payload, dict):
        raise ValueError("State event must be an object")
    tickets = tuple(_ticket_from_dict(item) for item in payload.get("tickets") or [])
    return EventSnapshot(
        id=int(payload["id"]),
        name=str(payload["name"]),
        share_url=str(payload["share_url"]),
        tickets_url=str(payload["tickets_url"]),
        label=payload.get("label"),
        sold_out=bool(payload.get("sold_out")),
        tickets=tickets,
        organiser_id=_optional_int(payload.get("organiser_id")),
    )


def _ticket_from_dict(payload: object) -> TicketSnapshot:
    if not isinstance(payload, dict):
        raise ValueError("State ticket must be an object")
    return TicketSnapshot(
        id=int(payload["id"]),
        name=str(payload["name"]),
        availability=TicketAvailability(str(payload["availability"])),
        price=payload.get("price"),
        on_sale_since=_optional_float(payload.get("on_sale_since")),
    )


def _existing_payload(path: Path) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _chat_id_from_value(value: object) -> str | None:
    if value is None:
        return None
    chat_id = str(value).strip()
    return chat_id or None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _battery_from_payload(payload: object) -> BatteryAlertState:
    if not isinstance(payload, dict):
        return BatteryAlertState()
    last_alert_at = _optional_float(payload.get("last_alert_at"))
    alerted = bool(payload.get("alerted"))
    if alerted and last_alert_at is None:
        last_alert_at = 0.0
    return BatteryAlertState(alerted=alerted, last_alert_at=last_alert_at)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
