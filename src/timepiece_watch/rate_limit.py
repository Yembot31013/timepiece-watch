from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from timepiece_watch.models import EventSnapshot, TicketAvailability
from timepiece_watch.status import event_availability, is_open

JitterFn = Callable[[float], float]


@dataclass(frozen=True)
class RatePolicy:
    idle_seconds: float = 90.0
    on_sale_seconds: float = 45.0
    coming_soon_seconds: float = 25.0
    restock_seconds: float = 180.0
    error_base_seconds: float = 30.0
    error_max_seconds: float = 1800.0
    jitter_ratio: float = 0.15


@dataclass(frozen=True)
class RateDecision:
    sleep_seconds: float
    reason: str


def select_event_ids_to_fetch(
    listed: Sequence[EventSnapshot],
    previous: Mapping[int, EventSnapshot],
    last_fetched_at: Mapping[int, float] | None = None,
    now: float = 0.0,
    policy: RatePolicy | None = None,
) -> frozenset[int]:
    fetched = last_fetched_at or {}
    active_policy = policy or RatePolicy()
    selected: set[int] = set()
    for event in listed:
        prior = previous.get(event.id)
        if prior is None:
            selected.add(event.id)
            continue
        prior_state = event_availability(prior)
        if is_open(prior_state):
            selected.add(event.id)
            continue
        if not event.sold_out:
            selected.add(event.id)
            continue
        last_check = fetched.get(event.id)
        if last_check is None or (now - last_check) >= active_policy.restock_seconds:
            selected.add(event.id)
    return frozenset(selected)


def next_sleep(
    events: Sequence[EventSnapshot],
    consecutive_errors: int,
    retry_after: float | None,
    jitter: JitterFn,
    policy: RatePolicy | None = None,
) -> RateDecision:
    active_policy = policy or RatePolicy()
    if retry_after is not None and retry_after > 0:
        return RateDecision(sleep_seconds=_with_jitter(retry_after, jitter), reason="retry_after")
    if consecutive_errors > 0:
        exponent = min(consecutive_errors - 1, 8)
        delay = min(
            active_policy.error_base_seconds * (2**exponent),
            active_policy.error_max_seconds,
        )
        return RateDecision(sleep_seconds=_with_jitter(delay, jitter), reason="error_backoff")

    states = {event_availability(event) for event in events}
    if TicketAvailability.COMING_SOON in states:
        return RateDecision(
            sleep_seconds=_with_jitter(active_policy.coming_soon_seconds, jitter),
            reason="coming_soon",
        )
    if TicketAvailability.ON_SALE in states:
        return RateDecision(
            sleep_seconds=_with_jitter(active_policy.on_sale_seconds, jitter),
            reason="on_sale",
        )
    if any(is_open(state) for state in states):
        return RateDecision(
            sleep_seconds=_with_jitter(active_policy.coming_soon_seconds, jitter),
            reason="listed",
        )
    return RateDecision(
        sleep_seconds=_with_jitter(active_policy.idle_seconds, jitter),
        reason="idle",
    )


def _with_jitter(seconds: float, jitter: JitterFn) -> float:
    extra = jitter(seconds)
    return max(1.0, seconds + extra)
