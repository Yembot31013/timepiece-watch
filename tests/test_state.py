import pytest

from tests.conftest import event, ticket
from timepiece_watch.battery import BatteryAlertState
from timepiece_watch.models import TicketAvailability
from timepiece_watch.state import load_battery_state, load_state, load_telegram_chat_id, save_state


def test_state_round_trip(tmp_path) -> None:
    path = tmp_path / "state.json"
    snapshot = event(
        tickets=(ticket(availability=TicketAvailability.COMING_SOON, on_sale_since=None),),
    )
    live = event(tickets=(ticket(on_sale_since=123.25),))

    save_state(path, {snapshot.id: snapshot})
    loaded = load_state(path)
    assert loaded[snapshot.id] == snapshot

    save_state(path, {live.id: live})
    assert load_state(path)[live.id].tickets[0].on_sale_since == 123.25


def test_missing_state_file_returns_empty(tmp_path) -> None:
    assert load_state(tmp_path / "missing.json") == {}


def test_invalid_state_json_is_rejected(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_state(path)


def test_state_events_must_be_a_list(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"events": null}', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid structure"):
        load_state(path)


def test_battery_state_round_trip(tmp_path) -> None:
    path = tmp_path / "state.json"
    snapshot = event(tickets=(ticket(),))
    battery = BatteryAlertState(alerted=True, last_alert_at=123.5)

    save_state(path, {snapshot.id: snapshot}, battery)

    assert load_state(path)[snapshot.id] == snapshot
    assert load_battery_state(path) == battery


def test_missing_or_invalid_battery_state_is_default(tmp_path) -> None:
    path = tmp_path / "state.json"
    assert load_battery_state(tmp_path / "missing.json") == BatteryAlertState()

    save_state(path, {})
    assert load_battery_state(path) == BatteryAlertState()

    path.write_text('{"events": [], "battery": "nope"}', encoding="utf-8")
    assert load_battery_state(path) == BatteryAlertState()

    path.write_text("{not json", encoding="utf-8")
    assert load_battery_state(path) == BatteryAlertState()

    path.write_text("[]", encoding="utf-8")
    assert load_battery_state(path) == BatteryAlertState()

    path.write_text(
        '{"events": [], "battery": {"alerted": true, "last_alert_at": "nope"}}',
        encoding="utf-8",
    )
    assert load_battery_state(path) == BatteryAlertState(alerted=True, last_alert_at=0.0)


def test_telegram_chat_id_round_trip_and_preserve(tmp_path) -> None:
    path = tmp_path / "state.json"
    snapshot = event(tickets=(ticket(),))
    save_state(path, {snapshot.id: snapshot}, telegram_chat_id="-100222")

    assert load_telegram_chat_id(path) == "-100222"
    assert load_telegram_chat_id(tmp_path / "missing.json") is None

    save_state(path, {snapshot.id: snapshot})
    assert load_telegram_chat_id(path) == "-100222"


def test_save_state_is_atomic(tmp_path, monkeypatch) -> None:
    """A crash during write must not leave a partial file at the target path."""
    import os

    path = tmp_path / "state.json"
    snapshot = event(tickets=(ticket(availability=TicketAvailability.COMING_SOON),))

    # First save succeeds; ensure a .tmp sibling does not persist.
    save_state(path, {snapshot.id: snapshot})
    assert not (tmp_path / "state.tmp").exists()
    assert path.exists()
