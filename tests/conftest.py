from timepiece_watch.models import EventSnapshot, TicketAvailability, TicketSnapshot


def ticket(
    ticket_id: int = 1,
    name: str = "Entry 8-8:30pm",
    availability: TicketAvailability = TicketAvailability.ON_SALE,
    on_sale_since: float | None = None,
) -> TicketSnapshot:
    return TicketSnapshot(
        id=ticket_id,
        name=name,
        availability=availability,
        price="4.00",
        on_sale_since=on_sale_since,
    )


def event(
    event_id: int = 350258228,
    name: str = "VK FEST 26",
    sold_out: bool = False,
    tickets: tuple[TicketSnapshot, ...] = (),
    label: str | None = "On sale now",
    organiser_id: int | None = 5486166,
) -> EventSnapshot:
    return EventSnapshot(
        id=event_id,
        name=name,
        share_url=f"https://fixr.co/event/example-tickets-{event_id}",
        tickets_url=f"https://fixr.co/event/example-tickets-{event_id}/tickets",
        label=label,
        sold_out=sold_out,
        tickets=tickets,
        organiser_id=organiser_id,
    )
