from tests.conftest import event, ticket
from timepiece_watch.models import AlertKind, EventSnapshot, TicketAvailability
from timepiece_watch.rate_limit import RatePolicy
from timepiece_watch.watcher import poll_once


class FakeClient:
    def __init__(self, listed: tuple[EventSnapshot, ...], details: dict[int, EventSnapshot]) -> None:
        self.listed = listed
        self.details = details
        self.event_calls: list[int] = []

    def fetch_venue(self, venue_id: int) -> tuple[EventSnapshot, ...]:
        assert venue_id == 2783
        return self.listed

    def fetch_event(self, event_id: int) -> EventSnapshot:
        self.event_calls.append(event_id)
        return self.details[event_id]


def test_poll_skips_known_sold_out_and_alerts_drop() -> None:
    sold = event(
        event_id=1,
        name="SKETCH",
        sold_out=True,
        tickets=(ticket(availability=TicketAvailability.SOLD_OUT),),
    )
    pending = event(
        event_id=2,
        name="UV Hi Vis Rave",
        tickets=(ticket(availability=TicketAvailability.COMING_SOON),),
    )
    live = event(
        event_id=2,
        name="UV Hi Vis Rave",
        tickets=(ticket(availability=TicketAvailability.ON_SALE),),
    )
    listed = (
        event(event_id=1, name="SKETCH", sold_out=True, tickets=()),
        event(event_id=2, name="UV Hi Vis Rave", sold_out=False, tickets=()),
    )
    client = FakeClient(listed, {2: live})

    result = poll_once(
        client,
        {1: sold, 2: pending},
        last_fetched_at={1: 1_000.0},
        now=1_010.0,
    )

    assert client.event_calls == [2]
    assert [alert.kind for alert in result.alerts] == [AlertKind.ON_SALE]
    assert result.events[2].tickets[0].availability == TicketAvailability.ON_SALE
    assert result.sleep_reason == "on_sale"


def test_poll_alerts_on_sale_when_first_added_to_state() -> None:
    listed = (event(event_id=350258228, sold_out=False, tickets=()),)
    live = event(
        event_id=350258228,
        name="VK FEST 26",
        label="Just added",
        tickets=(ticket(availability=TicketAvailability.ON_SALE),),
    )
    client = FakeClient(listed, {350258228: live})

    result = poll_once(client, {})

    assert [alert.kind for alert in result.alerts] == [AlertKind.ON_SALE]
    assert result.alerts[0].event.name == "VK FEST 26"
    assert result.alerts[0].tickets[0].availability == TicketAvailability.ON_SALE


def test_poll_uses_coming_soon_interval() -> None:
    listed = (event(event_id=7, sold_out=False, tickets=()),)
    details = {
        7: event(
            event_id=7,
            tickets=(ticket(availability=TicketAvailability.COMING_SOON),),
        )
    }
    client = FakeClient(listed, details)

    result = poll_once(client, {7: details[7]})

    assert result.sleep_reason == "coming_soon"
    assert result.alerts == ()


def test_poll_drops_other_organisers() -> None:
    listed = (event(event_id=8, sold_out=False, tickets=()),)
    other = event(
        event_id=8,
        name="TIMEPIECE SILENT DISCO",
        organiser_id=509037417,
        tickets=(ticket(availability=TicketAvailability.ON_SALE),),
    )
    client = FakeClient(listed, {8: other})

    result = poll_once(client, {})

    assert result.events == {}


def test_poll_keeps_extra_organiser_when_allowlisted() -> None:
    listed = (event(event_id=8, sold_out=False, tickets=()),)
    other = event(
        event_id=8,
        name="TIMEPIECE SILENT DISCO",
        organiser_id=509037417,
        tickets=(ticket(availability=TicketAvailability.ON_SALE),),
    )
    client = FakeClient(listed, {8: other})

    result = poll_once(client, {}, organiser_ids=frozenset({5486166, 509037417}))

    assert 8 in result.events
    assert [alert.kind for alert in result.alerts] == [AlertKind.ON_SALE]


def test_poll_alerts_sold_fast_when_slot_dies_quickly() -> None:
    listed = (event(event_id=9, sold_out=False, tickets=()),)
    previous = event(
        event_id=9,
        tickets=(ticket(on_sale_since=1_000.0),),
    )
    gone = event(
        event_id=9,
        sold_out=True,
        tickets=(ticket(availability=TicketAvailability.SOLD_OUT),),
    )
    client = FakeClient(listed, {9: gone})

    result = poll_once(client, {9: previous}, now=1_045.0, sold_fast_seconds=600.0)

    assert [alert.kind for alert in result.alerts] == [AlertKind.SOLD_FAST]
    assert result.alerts[0].sold_after_seconds == 45.0


def test_poll_refetches_stale_sold_out_and_alerts_restock() -> None:
    sold = event(
        event_id=1,
        name="SKETCH",
        sold_out=True,
        tickets=(ticket(availability=TicketAvailability.SOLD_OUT),),
    )
    restocked = event(
        event_id=1,
        name="SKETCH",
        sold_out=False,
        tickets=(ticket(availability=TicketAvailability.ON_SALE),),
    )
    listed = (event(event_id=1, name="SKETCH", sold_out=True, tickets=()),)
    client = FakeClient(listed, {1: restocked})

    result = poll_once(
        client,
        {1: sold},
        last_fetched_at={1: 0.0},
        now=200.0,
        policy=RatePolicy(restock_seconds=180.0),
    )

    assert client.event_calls == [1]
    assert [alert.kind for alert in result.alerts] == [AlertKind.ON_SALE]
    assert result.last_fetched_at[1] == 200.0


