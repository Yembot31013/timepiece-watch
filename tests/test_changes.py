from tests.conftest import event, ticket
from timepiece_watch.changes import detect_alerts, stamp_on_sale_times
from timepiece_watch.models import AlertKind, TicketAvailability


def test_first_snapshot_alerts_on_sale() -> None:
    current = event(
        tickets=(ticket(availability=TicketAvailability.ON_SALE),),
    )
    alerts = detect_alerts({}, (current,))
    assert [alert.kind for alert in alerts] == [AlertKind.ON_SALE]
    assert alerts[0].tickets[0].name == "Entry 8-8:30pm"


def test_first_snapshot_alerts_coming_soon() -> None:
    current = event(
        tickets=(ticket(availability=TicketAvailability.COMING_SOON),),
    )
    alerts = detect_alerts({}, (current,))
    assert [alert.kind for alert in alerts] == [AlertKind.COMING_SOON]


def test_first_snapshot_does_not_alert_sold_out_only() -> None:
    current = event(
        sold_out=True,
        tickets=(ticket(availability=TicketAvailability.SOLD_OUT),),
    )
    assert detect_alerts({}, (current,)) == ()


def test_first_snapshot_does_not_alert_expired_only() -> None:
    current = event(tickets=(ticket(availability=TicketAvailability.EXPIRED),))
    assert detect_alerts({}, (current,)) == ()


def test_new_sold_out_event_does_not_alert() -> None:
    known = event(event_id=1, sold_out=True, tickets=(ticket(availability=TicketAvailability.SOLD_OUT),))
    incoming = event(
        event_id=2,
        name="SKETCH",
        sold_out=True,
        tickets=(ticket(availability=TicketAvailability.SOLD_OUT),),
    )
    assert detect_alerts({known.id: known}, (known, incoming)) == ()


def test_new_event_and_coming_soon_alerts() -> None:
    known = event(event_id=1, name="Old", sold_out=True, tickets=(ticket(availability=TicketAvailability.SOLD_OUT),))
    incoming = event(
        event_id=2,
        name="UV Hi Vis Rave",
        tickets=(ticket(availability=TicketAvailability.COMING_SOON),),
    )

    alerts = detect_alerts({known.id: known}, (known, incoming))
    kinds = [alert.kind for alert in alerts]

    assert kinds == [AlertKind.NEW_EVENT, AlertKind.COMING_SOON]
    assert alerts[0].event.name == "UV Hi Vis Rave"


def test_coming_soon_to_on_sale_is_the_drop_alert() -> None:
    previous = event(
        tickets=(ticket(availability=TicketAvailability.COMING_SOON),),
    )
    current = event(
        tickets=(ticket(availability=TicketAvailability.ON_SALE),),
    )

    alerts = detect_alerts({previous.id: previous}, (current,))

    assert [alert.kind for alert in alerts] == [AlertKind.ON_SALE]
    assert alerts[0].tickets[0].name == "Entry 8-8:30pm"


def test_on_sale_to_sold_out_soon_after_open_is_sold_fast() -> None:
    previous = event(
        tickets=(ticket(availability=TicketAvailability.ON_SALE, on_sale_since=100.0),),
        sold_out=False,
    )
    current = event(
        tickets=(ticket(availability=TicketAvailability.SOLD_OUT),),
        sold_out=True,
    )

    alerts = detect_alerts({previous.id: previous}, (current,), now=160.0, sold_fast_seconds=600.0)

    assert [alert.kind for alert in alerts] == [AlertKind.SOLD_FAST]
    assert alerts[0].sold_after_seconds == 60.0
    assert alerts[0].tickets[0].name == "Entry 8-8:30pm"


def test_on_sale_to_sold_out_after_long_window_is_normal_sold_out() -> None:
    previous = event(
        tickets=(ticket(availability=TicketAvailability.ON_SALE, on_sale_since=100.0),),
        sold_out=False,
    )
    current = event(
        tickets=(ticket(availability=TicketAvailability.SOLD_OUT),),
        sold_out=True,
    )

    alerts = detect_alerts({previous.id: previous}, (current,), now=100.0 + 601.0, sold_fast_seconds=600.0)

    assert [alert.kind for alert in alerts] == [AlertKind.SOLD_OUT]


def test_legacy_on_sale_without_timestamp_is_not_sold_fast() -> None:
    previous = event(tickets=(ticket(availability=TicketAvailability.ON_SALE),), sold_out=False)
    current = event(tickets=(ticket(availability=TicketAvailability.SOLD_OUT),), sold_out=True)

    alerts = detect_alerts({previous.id: previous}, (current,), now=200.0, sold_fast_seconds=600.0)

    assert [alert.kind for alert in alerts] == [AlertKind.SOLD_OUT]


def test_one_slot_sold_fast_while_others_stay_on_sale() -> None:
    previous = event(
        tickets=(
            ticket(ticket_id=1, name="8-8:30pm", on_sale_since=100.0),
            ticket(ticket_id=2, name="9-9:30pm", on_sale_since=100.0),
        )
    )
    current = event(
        tickets=(
            ticket(ticket_id=1, name="8-8:30pm"),
            ticket(ticket_id=2, name="9-9:30pm", availability=TicketAvailability.SOLD_OUT),
        )
    )

    alerts = detect_alerts({previous.id: previous}, (current,), now=140.0, sold_fast_seconds=600.0)

    assert [alert.kind for alert in alerts] == [AlertKind.SOLD_FAST]
    assert alerts[0].tickets[0].name == "9-9:30pm"


def test_stamp_sets_on_sale_since_only_when_newly_buyable() -> None:
    previous = event(
        tickets=(
            ticket(ticket_id=1, availability=TicketAvailability.COMING_SOON),
            ticket(ticket_id=2, on_sale_since=50.0),
            ticket(ticket_id=3),
        )
    )
    current = {
        previous.id: event(
            tickets=(
                ticket(ticket_id=1),
                ticket(ticket_id=2),
                ticket(ticket_id=3),
            )
        )
    }

    stamped = stamp_on_sale_times({previous.id: previous}, current, now=80.0)
    tickets = {item.id: item for item in stamped[previous.id].tickets}

    assert tickets[1].on_sale_since == 80.0
    assert tickets[2].on_sale_since == 50.0
    assert tickets[3].on_sale_since is None


def test_on_sale_to_sold_out_alerts_once() -> None:
    previous = event(
        tickets=(ticket(availability=TicketAvailability.ON_SALE),),
        sold_out=False,
    )
    current = event(
        tickets=(ticket(availability=TicketAvailability.SOLD_OUT),),
        sold_out=True,
        label="Sold out",
    )

    alerts = detect_alerts({previous.id: previous}, (current,))

    assert [alert.kind for alert in alerts] == [AlertKind.SOLD_OUT]


def test_coming_soon_to_sold_out_alerts() -> None:
    """Tickets that skip ON_SALE and flip directly to SOLD_OUT must still alert."""
    previous = event(tickets=(ticket(availability=TicketAvailability.COMING_SOON),))
    current = event(
        tickets=(ticket(availability=TicketAvailability.SOLD_OUT),),
        sold_out=True,
    )

    alerts = detect_alerts({previous.id: previous}, (current,))

    assert [alert.kind for alert in alerts] == [AlertKind.SOLD_OUT]


def test_unchanged_on_sale_does_not_repeat() -> None:
    snapshot = event(tickets=(ticket(availability=TicketAvailability.ON_SALE),))
    assert detect_alerts({snapshot.id: snapshot}, (snapshot,)) == ()


def test_sold_out_to_listed_alerts() -> None:
    previous = event(
        tickets=(ticket(availability=TicketAvailability.SOLD_OUT),),
        sold_out=True,
    )
    current = event(
        tickets=(ticket(availability=TicketAvailability.COMING_SOON),),
        sold_out=False,
    )

    alerts = detect_alerts({previous.id: previous}, (current,))
    assert [alert.kind for alert in alerts] == [AlertKind.COMING_SOON]


def test_sold_out_to_on_sale_is_a_restock_alert() -> None:
    previous = event(
        tickets=(ticket(availability=TicketAvailability.SOLD_OUT),),
        sold_out=True,
    )
    current = event(
        tickets=(ticket(availability=TicketAvailability.ON_SALE),),
        sold_out=False,
    )

    alerts = detect_alerts({previous.id: previous}, (current,))

    assert [alert.kind for alert in alerts] == [AlertKind.ON_SALE]
