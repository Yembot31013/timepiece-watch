from tests.conftest import event, ticket
from timepiece_watch.models import TicketAvailability
from timepiece_watch.rate_limit import RatePolicy, next_sleep, select_event_ids_to_fetch


def test_skips_recently_checked_sold_out_events() -> None:
    sold_out = event(
        event_id=1,
        sold_out=True,
        tickets=(ticket(availability=TicketAvailability.SOLD_OUT),),
    )
    live = event(event_id=2, sold_out=False, tickets=())
    previous = {sold_out.id: sold_out}

    selected = select_event_ids_to_fetch(
        (sold_out, live),
        previous,
        last_fetched_at={1: 100.0},
        now=150.0,
        policy=RatePolicy(restock_seconds=180.0),
    )
    assert selected == frozenset({2})


def test_refetches_stale_sold_out_for_restock() -> None:
    sold_out = event(
        event_id=1,
        sold_out=True,
        tickets=(ticket(availability=TicketAvailability.SOLD_OUT),),
    )

    selected = select_event_ids_to_fetch(
        (sold_out,),
        {sold_out.id: sold_out},
        last_fetched_at={1: 0.0},
        now=200.0,
        policy=RatePolicy(restock_seconds=180.0),
    )
    assert selected == frozenset({1})


def test_refetches_coming_soon_even_if_venue_says_sold_out() -> None:
    previous = event(
        event_id=9,
        sold_out=False,
        tickets=(ticket(availability=TicketAvailability.COMING_SOON),),
    )
    listed = event(event_id=9, sold_out=True, tickets=())

    assert select_event_ids_to_fetch((listed,), {previous.id: previous}) == frozenset({9})


def test_refetches_when_previously_sold_out_event_is_listed_as_open() -> None:
    previous = event(
        event_id=3,
        sold_out=True,
        tickets=(ticket(availability=TicketAvailability.SOLD_OUT),),
    )
    listed = event(event_id=3, sold_out=False, tickets=())

    assert select_event_ids_to_fetch((listed,), {previous.id: previous}) == frozenset({3})


def test_idle_sleep_when_nothing_is_pending() -> None:
    snapshots = (
        event(sold_out=True, tickets=(ticket(availability=TicketAvailability.SOLD_OUT),)),
    )
    decision = next_sleep(snapshots, consecutive_errors=0, retry_after=None, jitter=lambda _: 0.0)

    assert decision.reason == "idle"
    assert decision.sleep_seconds == RatePolicy().idle_seconds


def test_faster_sleep_when_listed_tickets_are_pending() -> None:
    snapshots = (
        event(tickets=(ticket(availability=TicketAvailability.COMING_SOON),)),
    )
    decision = next_sleep(snapshots, consecutive_errors=0, retry_after=None, jitter=lambda _: 0.0)

    assert decision.reason == "coming_soon"
    assert decision.sleep_seconds == RatePolicy().coming_soon_seconds


def test_on_sale_sleep_is_between_drop_and_idle() -> None:
    snapshots = (
        event(tickets=(ticket(availability=TicketAvailability.ON_SALE),)),
    )
    decision = next_sleep(snapshots, consecutive_errors=0, retry_after=None, jitter=lambda _: 0.0)

    assert decision.reason == "on_sale"
    assert decision.sleep_seconds == RatePolicy().on_sale_seconds


def test_first_error_uses_thirty_second_base() -> None:
    decision = next_sleep((), consecutive_errors=1, retry_after=None, jitter=lambda _: 0.0)
    assert decision.reason == "error_backoff"
    assert decision.sleep_seconds == RatePolicy().error_base_seconds
    assert decision.sleep_seconds == 30.0


def test_backoff_uses_retry_after_and_exponential_cap() -> None:
    policy = RatePolicy()
    retry = next_sleep((), consecutive_errors=1, retry_after=12.0, jitter=lambda _: 0.0)
    assert retry.sleep_seconds == 12.0
    assert retry.reason == "retry_after"

    backed_off = next_sleep((), consecutive_errors=8, retry_after=None, jitter=lambda _: 0.0)
    assert backed_off.reason == "error_backoff"
    assert backed_off.sleep_seconds == policy.error_max_seconds
