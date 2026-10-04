from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace

from timepiece_watch.models import Alert, AlertKind, EventSnapshot, TicketAvailability, TicketSnapshot
from timepiece_watch.status import event_availability, event_is_open, is_open

DEFAULT_SOLD_FAST_SECONDS = 600.0


def detect_alerts(
    previous: Mapping[int, EventSnapshot],
    current: Sequence[EventSnapshot],
    now: float | None = None,
    sold_fast_seconds: float = DEFAULT_SOLD_FAST_SECONDS,
) -> tuple[Alert, ...]:
    alerts: list[Alert] = []
    for event in current:
        prior = previous.get(event.id)
        if prior is None:
            if previous and event_is_open(event):
                alerts.append(Alert(kind=AlertKind.NEW_EVENT, event=event))
            alerts.extend(
                _availability_alerts(
                    event,
                    prior_tickets=(),
                    now=now,
                    sold_fast_seconds=sold_fast_seconds,
                )
            )
            continue
        alerts.extend(
            _availability_alerts(
                event,
                prior_tickets=prior.tickets,
                now=now,
                sold_fast_seconds=sold_fast_seconds,
            )
        )
    return tuple(alerts)


def stamp_on_sale_times(
    previous: Mapping[int, EventSnapshot],
    current: Mapping[int, EventSnapshot],
    now: float,
) -> dict[int, EventSnapshot]:
    return {
        event_id: _stamp_event(previous.get(event_id), event, now)
        for event_id, event in current.items()
    }


def _availability_alerts(
    event: EventSnapshot,
    prior_tickets: Sequence[TicketSnapshot],
    now: float | None,
    sold_fast_seconds: float,
) -> tuple[Alert, ...]:
    prior_by_id = {ticket.id: ticket for ticket in prior_tickets}
    changed_open: dict[TicketAvailability, list[TicketSnapshot]] = defaultdict(list)
    for ticket in event.tickets:
        if not is_open(ticket.availability):
            continue
        prior = prior_by_id.get(ticket.id)
        if prior is not None and prior.availability == ticket.availability:
            continue
        changed_open[ticket.availability].append(ticket)

    alerts: list[Alert] = []
    for availability, tickets in changed_open.items():
        alerts.append(
            Alert(kind=_kind_for_open(availability), event=event, tickets=tuple(tickets))
        )

    fast_ids: set[int] = set()
    if now is not None and sold_fast_seconds > 0:
        for ticket, elapsed in _sold_fast_tickets(event.tickets, prior_by_id, now, sold_fast_seconds):
            fast_ids.add(ticket.id)
            alerts.append(
                Alert(
                    kind=AlertKind.SOLD_FAST,
                    event=event,
                    tickets=(ticket,),
                    sold_after_seconds=elapsed,
                )
            )

    current_state = event_availability(event)
    prior_was_open = any(is_open(ticket.availability) for ticket in prior_by_id.values())
    if current_state == TicketAvailability.SOLD_OUT and prior_was_open and not changed_open:
        leftover = tuple(ticket for ticket in event.tickets if ticket.id not in fast_ids)
        if leftover:
            alerts.append(Alert(kind=AlertKind.SOLD_OUT, event=event, tickets=leftover))
    return tuple(alerts)


def _sold_fast_tickets(
    tickets: Sequence[TicketSnapshot],
    prior_by_id: Mapping[int, TicketSnapshot],
    now: float,
    sold_fast_seconds: float,
) -> tuple[tuple[TicketSnapshot, float], ...]:
    sold_fast: list[tuple[TicketSnapshot, float]] = []
    for ticket in tickets:
        if ticket.availability != TicketAvailability.SOLD_OUT:
            continue
        prior = prior_by_id.get(ticket.id)
        if prior is None or prior.availability != TicketAvailability.ON_SALE:
            continue
        if prior.on_sale_since is None:
            continue
        elapsed = now - prior.on_sale_since
        if 0 <= elapsed <= sold_fast_seconds:
            sold_fast.append((ticket, elapsed))
    return tuple(sold_fast)


def _stamp_event(prior: EventSnapshot | None, event: EventSnapshot, now: float) -> EventSnapshot:
    prior_by_id = {ticket.id: ticket for ticket in prior.tickets} if prior is not None else {}
    stamped = tuple(_stamp_ticket(prior_by_id.get(ticket.id), ticket, now) for ticket in event.tickets)
    return replace(event, tickets=stamped)


def _stamp_ticket(
    prior: TicketSnapshot | None,
    ticket: TicketSnapshot,
    now: float,
) -> TicketSnapshot:
    if ticket.availability != TicketAvailability.ON_SALE:
        return replace(ticket, on_sale_since=None)
    if prior is not None and prior.availability == TicketAvailability.ON_SALE:
        return replace(ticket, on_sale_since=prior.on_sale_since)
    return replace(ticket, on_sale_since=now)


def _kind_for_open(availability: TicketAvailability) -> AlertKind:
    if availability == TicketAvailability.ON_SALE:
        return AlertKind.ON_SALE
    return AlertKind.COMING_SOON
