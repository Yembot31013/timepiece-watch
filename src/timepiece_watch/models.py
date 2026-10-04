from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TicketAvailability(str, Enum):
    COMING_SOON = "coming_soon"
    ON_SALE = "on_sale"
    SOLD_OUT = "sold_out"
    EXPIRED = "expired"


class AlertKind(str, Enum):
    NEW_EVENT = "new_event"
    COMING_SOON = "coming_soon"
    ON_SALE = "on_sale"
    SOLD_OUT = "sold_out"
    SOLD_FAST = "sold_fast"


@dataclass(frozen=True)
class TicketSnapshot:
    id: int
    name: str
    availability: TicketAvailability
    price: str | None = None
    on_sale_since: float | None = None


@dataclass(frozen=True)
class EventSnapshot:
    id: int
    name: str
    share_url: str
    tickets_url: str
    label: str | None
    sold_out: bool
    tickets: tuple[TicketSnapshot, ...]
    organiser_id: int | None = None


@dataclass(frozen=True)
class Alert:
    kind: AlertKind
    event: EventSnapshot
    tickets: tuple[TicketSnapshot, ...] = ()
    sold_after_seconds: float | None = None
