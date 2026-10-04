from tests.conftest import event, ticket
from timepiece_watch.models import Alert, AlertKind, TicketAvailability
from timepiece_watch.notifier import format_alert_messages, format_status


def test_each_ticket_gets_its_own_message() -> None:
    snapshot = event(
        tickets=(
            ticket(ticket_id=1, name="Entry 8-8:30pm"),
            ticket(ticket_id=2, name="Entry 8:30-9pm"),
        )
    )
    messages = format_alert_messages(
        Alert(kind=AlertKind.ON_SALE, event=snapshot, tickets=snapshot.tickets)
    )

    assert len(messages) == 2
    assert "Entry 8-8:30pm" in messages[0]
    assert "Entry 8:30-9pm" not in messages[0]
    assert "Entry 8:30-9pm" in messages[1]
    assert "🟢" in messages[0]
    assert "<b>On sale</b>" in messages[0]
    assert "<b>VK FEST 26</b>" in messages[0]
    assert snapshot.tickets_url in messages[0]
    assert "£4.00" in messages[0]


def test_listed_ticket_uses_listed_copy() -> None:
    snapshot = event(tickets=(ticket(availability=TicketAvailability.COMING_SOON),))
    messages = format_alert_messages(
        Alert(kind=AlertKind.COMING_SOON, event=snapshot, tickets=snapshot.tickets)
    )

    assert len(messages) == 1
    assert "🟡" in messages[0]
    assert "<b>On sale soon</b>" in messages[0]
    assert "Get ready — tickets opening soon!" in messages[0]
    assert snapshot.tickets_url in messages[0]


def test_new_event_without_tickets_is_a_single_message() -> None:
    snapshot = event(tickets=(), label="Just added")
    messages = format_alert_messages(Alert(kind=AlertKind.NEW_EVENT, event=snapshot))

    assert len(messages) == 1
    assert "🆕" in messages[0]
    assert "<b>New event</b>" in messages[0]
    assert "<i>Just added</i>" in messages[0]
    assert snapshot.tickets_url in messages[0]


def test_coming_soon_event_without_tickets_has_get_ready() -> None:
    snapshot = event(tickets=())
    messages = format_alert_messages(Alert(kind=AlertKind.COMING_SOON, event=snapshot))

    assert len(messages) == 1
    assert "🟡" in messages[0]
    assert "<b>On sale soon</b>" in messages[0]
    assert "Get ready — tickets opening soon!" in messages[0]
    assert snapshot.tickets_url in messages[0]


def test_html_special_characters_are_escaped() -> None:
    snapshot = event(name="VK <Fest> & Co")
    messages = format_alert_messages(
        Alert(
            kind=AlertKind.SOLD_OUT,
            event=snapshot,
            tickets=(ticket(name="Entry 9-9:30pm & last"),),
        )
    )

    assert "VK &lt;Fest&gt; &amp; Co" in messages[0]
    assert "Entry 9-9:30pm &amp; last" in messages[0]
    assert "🔴" in messages[0]


def test_sold_fast_message_includes_how_long_it_was_on_sale() -> None:
    snapshot = event(tickets=(ticket(name="Entry 9-9:30pm"),))
    messages = format_alert_messages(
        Alert(
            kind=AlertKind.SOLD_FAST,
            event=snapshot,
            tickets=snapshot.tickets,
            sold_after_seconds=135.0,
        )
    )

    assert "⚡" in messages[0]
    assert "<b>Sold fast</b>" in messages[0]
    assert "Entry 9-9:30pm" in messages[0]
    assert "On sale for 2m 15s" in messages[0]
    assert snapshot.tickets_url in messages[0]
    assert "On sale for 45s" in format_alert_messages(
        Alert(kind=AlertKind.SOLD_FAST, event=snapshot, tickets=snapshot.tickets, sold_after_seconds=45)
    )[0]
    assert "On sale for 2m" in format_alert_messages(
        Alert(kind=AlertKind.SOLD_FAST, event=snapshot, tickets=snapshot.tickets, sold_after_seconds=120)
    )[0]


def test_format_status_empty_listings() -> None:
    assert "No Timepiece events" in format_status(())


def test_format_status_lists_each_slot() -> None:
    snapshot = event(tickets=(ticket(availability=TicketAvailability.COMING_SOON),))
    text = format_status((snapshot,))
    assert "Timepiece Nightclub" in text
    assert "coming_soon" in text
    assert "ON SALE SOON" in text
    assert snapshot.tickets_url in text


def test_format_status_includes_tickets_url_when_on_sale() -> None:
    snapshot = event(tickets=(ticket(availability=TicketAvailability.ON_SALE),))
    text = format_status((snapshot,))
    assert snapshot.tickets_url in text
