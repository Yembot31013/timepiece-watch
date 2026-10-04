from __future__ import annotations

from collections.abc import Sequence

from timepiece_watch.models import EventSnapshot, TicketAvailability

DEAD_AVAILABILITY = frozenset(
    {
        TicketAvailability.SOLD_OUT,
        TicketAvailability.EXPIRED,
    }
)


def classify_ticket(payload: object) -> TicketAvailability:
    if not isinstance(payload, dict):
        raise ValueError("ticket payload must be an object")

    if payload.get("expired"):
        return TicketAvailability.EXPIRED
    if payload.get("sold_out"):
        return TicketAvailability.SOLD_OUT
    if payload.get("not_yet_valid"):
        return TicketAvailability.COMING_SOON
    return TicketAvailability.ON_SALE


def classify_event(
    tickets: Sequence[TicketAvailability],
    event_sold_out: bool,
) -> TicketAvailability:
    if TicketAvailability.ON_SALE in tickets:
        return TicketAvailability.ON_SALE
    open_states = [state for state in tickets if is_open(state)]
    if open_states:
        return open_states[0]
    if tickets and all(state == TicketAvailability.EXPIRED for state in tickets):
        return TicketAvailability.EXPIRED
    if event_sold_out or TicketAvailability.SOLD_OUT in tickets:
        return TicketAvailability.SOLD_OUT
    return TicketAvailability.COMING_SOON


def event_availability(event: EventSnapshot) -> TicketAvailability:
    ticket_states = tuple(ticket.availability for ticket in event.tickets)
    return classify_event(ticket_states, event.sold_out)


def is_open(availability: TicketAvailability) -> bool:
    return availability not in DEAD_AVAILABILITY


def event_is_open(event: EventSnapshot) -> bool:
    return is_open(event_availability(event))
