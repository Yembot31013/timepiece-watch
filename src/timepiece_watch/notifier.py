from __future__ import annotations

from timepiece_watch.models import Alert, AlertKind, EventSnapshot, TicketAvailability, TicketSnapshot
from timepiece_watch.status import classify_event, is_open

_ALERT_STYLES: dict[AlertKind, tuple[str, str]] = {
    AlertKind.NEW_EVENT: ("🆕", "New event"),
    AlertKind.COMING_SOON: ("🟡", "On sale soon"),
    AlertKind.ON_SALE: ("🟢", "On sale"),
    AlertKind.SOLD_OUT: ("🔴", "Sold out"),
    AlertKind.SOLD_FAST: ("⚡", "Sold fast"),
}


def format_alert_messages(alert: Alert) -> tuple[str, ...]:
    if not alert.tickets:
        return (_event_message(alert),)
    return tuple(_ticket_message(alert, ticket) for ticket in alert.tickets)


def format_alert(alert: Alert) -> str:
    return "\n\n".join(format_alert_messages(alert))


def format_status(events: tuple[EventSnapshot, ...]) -> str:
    if not events:
        return "No Timepiece events listed right now."
    lines = ["Timepiece Nightclub"]
    for event in events:
        state = classify_event(
            tuple(ticket.availability for ticket in event.tickets),
            event.sold_out,
        )
        label = f" ({event.label})" if event.label else ""
        lines.append(f"  {event.name}  {state.value.upper()}{label}")
        for ticket in event.tickets:
            price = f"  £{ticket.price}" if ticket.price else ""
            lines.append(f"    - {ticket.name}: {ticket.availability.value}{price}")
        if is_open(state):
            prefix = "    ON SALE SOON  " if state == TicketAvailability.COMING_SOON else "    "
            lines.append(f"{prefix}{event.tickets_url}")
    return "\n".join(lines)


def _event_message(alert: Alert) -> str:
    emoji, title = _style(alert.kind)
    lines = [
        f"{emoji} <b>{_escape(title)}</b>",
        f"<b>{_escape(alert.event.name)}</b>",
    ]
    if alert.event.label:
        lines.append(f"<i>{_escape(alert.event.label)}</i>")
    if alert.kind == AlertKind.COMING_SOON:
        lines.append("Get ready — tickets opening soon!")
    lines.extend(["", alert.event.tickets_url])
    return "\n".join(lines)


def _ticket_message(alert: Alert, ticket: TicketSnapshot) -> str:
    emoji, title = _style(alert.kind)
    lines = [
        f"{emoji} <b>{_escape(title)}</b>",
        f"<b>{_escape(alert.event.name)}</b>",
        _escape(ticket.name),
    ]
    if ticket.price:
        lines.append(f"£{_escape(ticket.price)}")
    if alert.kind == AlertKind.COMING_SOON:
        lines.append("Get ready — tickets opening soon!")
    elif alert.kind == AlertKind.SOLD_FAST and alert.sold_after_seconds is not None:
        lines.append(f"On sale for {_format_duration(alert.sold_after_seconds)}")
    lines.extend(["", alert.event.tickets_url])
    return "\n".join(lines)


def _format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    minutes, remainder = divmod(total, 60)
    if minutes == 0:
        return f"{remainder}s"
    if remainder == 0:
        return f"{minutes}m"
    return f"{minutes}m {remainder}s"


def _style(kind: AlertKind) -> tuple[str, str]:
    return _ALERT_STYLES.get(kind, ("•", kind.value.replace("_", " ").title()))


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
