from __future__ import annotations

import time
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Protocol

from timepiece_watch.changes import DEFAULT_SOLD_FAST_SECONDS, detect_alerts, stamp_on_sale_times
from timepiece_watch.client import TIMEPIECE_SALES_ACCOUNT_ID, TIMEPIECE_VENUE_ID
from timepiece_watch.models import Alert, EventSnapshot
from timepiece_watch.rate_limit import RateDecision, RatePolicy, next_sleep, select_event_ids_to_fetch


class VenueClient(Protocol):
    def fetch_venue(self, venue_id: int) -> tuple[EventSnapshot, ...]:
        ...

    def fetch_event(self, event_id: int) -> EventSnapshot:
        ...


@dataclass(frozen=True)
class PollResult:
    events: dict[int, EventSnapshot]
    alerts: tuple[Alert, ...]
    sleep_seconds: float
    sleep_reason: str
    last_fetched_at: dict[int, float]


def poll_once(
    client: VenueClient,
    previous: Mapping[int, EventSnapshot],
    venue_id: int = TIMEPIECE_VENUE_ID,
    consecutive_errors: int = 0,
    retry_after: float | None = None,
    last_fetched_at: Mapping[int, float] | None = None,
    now: float | None = None,
    policy: RatePolicy | None = None,
    organiser_ids: Collection[int] | None = None,
    sold_fast_seconds: float = DEFAULT_SOLD_FAST_SECONDS,
) -> PollResult:
    active_policy = policy or RatePolicy()
    clock = time.time() if now is None else now
    fetched = dict(last_fetched_at or {})
    listed = client.fetch_venue(venue_id)
    fetch_ids = select_event_ids_to_fetch(
        listed,
        previous,
        last_fetched_at=fetched,
        now=clock,
        policy=active_policy,
    )
    merged: dict[int, EventSnapshot] = {}
    for event in listed:
        if event.id in fetch_ids:
            merged[event.id] = client.fetch_event(event.id)
            fetched[event.id] = clock
        else:
            merged[event.id] = previous.get(event.id, event)

    allowed = frozenset(organiser_ids) if organiser_ids is not None else frozenset(
        {TIMEPIECE_SALES_ACCOUNT_ID}
    )
    owned = stamp_on_sale_times(previous, _select_owned_events(merged, allowed), clock)
    alerts = detect_alerts(
        previous,
        tuple(owned.values()),
        now=clock,
        sold_fast_seconds=sold_fast_seconds,
    )
    decision = _decision_for(tuple(owned.values()), consecutive_errors, retry_after, active_policy)
    return PollResult(
        events=owned,
        alerts=alerts,
        sleep_seconds=decision.sleep_seconds,
        sleep_reason=decision.reason,
        last_fetched_at=fetched,
    )


def _select_owned_events(
    snapshots: Mapping[int, EventSnapshot],
    organiser_ids: frozenset[int],
) -> dict[int, EventSnapshot]:
    return {
        event_id: snapshot
        for event_id, snapshot in snapshots.items()
        if snapshot.organiser_id is None or snapshot.organiser_id in organiser_ids
    }


def _decision_for(
    events: tuple[EventSnapshot, ...],
    consecutive_errors: int,
    retry_after: float | None,
    policy: RatePolicy,
) -> RateDecision:
    return next_sleep(
        events,
        consecutive_errors=consecutive_errors,
        retry_after=retry_after,
        jitter=lambda _seconds: 0.0,
        policy=policy,
    )
