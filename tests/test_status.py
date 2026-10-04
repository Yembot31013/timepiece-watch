import pytest

from timepiece_watch.models import TicketAvailability
from timepiece_watch.status import classify_event, classify_ticket, is_open


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"expired": True, "sold_out": True, "not_yet_valid": False}, TicketAvailability.EXPIRED),
        ({"expired": False, "sold_out": True, "not_yet_valid": False}, TicketAvailability.SOLD_OUT),
        ({"expired": False, "sold_out": False, "not_yet_valid": True}, TicketAvailability.COMING_SOON),
        ({"expired": False, "sold_out": False, "not_yet_valid": False}, TicketAvailability.ON_SALE),
    ],
)
def test_classify_ticket(payload: dict, expected: TicketAvailability) -> None:
    assert classify_ticket(payload) == expected


def test_classify_ticket_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="ticket payload"):
        classify_ticket(["not", "a", "dict"])  # type: ignore[arg-type]


def test_event_on_sale_wins_over_other_slots() -> None:
    result = classify_event(
        (
            TicketAvailability.SOLD_OUT,
            TicketAvailability.COMING_SOON,
            TicketAvailability.ON_SALE,
        ),
        event_sold_out=False,
    )
    assert result == TicketAvailability.ON_SALE


def test_event_coming_soon_when_no_buyable_slots() -> None:
    result = classify_event(
        (TicketAvailability.COMING_SOON, TicketAvailability.SOLD_OUT),
        event_sold_out=False,
    )
    assert result == TicketAvailability.COMING_SOON


def test_event_uses_sold_out_flag_when_tickets_missing() -> None:
    assert classify_event((), event_sold_out=True) == TicketAvailability.SOLD_OUT
    assert classify_event((), event_sold_out=False) == TicketAvailability.COMING_SOON


def test_event_all_expired() -> None:
    assert classify_event((TicketAvailability.EXPIRED,), event_sold_out=False) == TicketAvailability.EXPIRED


def test_only_sold_out_and_expired_are_dead() -> None:
    assert is_open(TicketAvailability.ON_SALE)
    assert is_open(TicketAvailability.COMING_SOON)
    assert not is_open(TicketAvailability.SOLD_OUT)
    assert not is_open(TicketAvailability.EXPIRED)
