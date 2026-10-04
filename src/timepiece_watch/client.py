from __future__ import annotations

import datetime
import json
import time
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from timepiece_watch.models import EventSnapshot, TicketSnapshot
from timepiece_watch.status import classify_ticket

DEFAULT_BASE_URL = "https://api.fixr.co/api/v2/app"
TIMEPIECE_VENUE_ID = 2783
TIMEPIECE_SALES_ACCOUNT_ID = 5486166
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class FixrError(Exception):
    """Raised when a FIXR request or payload cannot be used."""


class FixrHttpError(FixrError):
    def __init__(self, message: str, status_code: int, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class FixrClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 30.0,
        min_interval_seconds: float = 0.0,
        network_retries: int = 3,
        retry_sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._min_interval_seconds = min_interval_seconds
        self._last_request_at = 0.0
        self._network_retries = max(1, network_retries)
        self._retry_sleep = retry_sleep

    def fetch_venue(self, venue_id: int) -> tuple[EventSnapshot, ...]:
        payload = self._get(f"/venue/{venue_id}")
        events = payload.get("events")
        if not isinstance(events, list):
            raise ValueError("FIXR payload is missing a venue event list")
        return tuple(_parse_event(item, include_tickets=False) for item in events)

    def fetch_event(self, event_id: int) -> EventSnapshot:
        payload = self._get(f"/event/{event_id}")
        return _parse_event(payload, include_tickets=True)

    def _get(self, path: str) -> dict[str, Any]:
        separator = "&" if "?" in path else "?"
        cache_busting_path = f"{path}{separator}_ts={int(time.time() * 1000)}"
        last_error: BaseException | None = None
        for attempt in range(self._network_retries):
            self._throttle()
            request = Request(
                f"{self._base_url}{cache_busting_path}",
                headers={
                    "User-Agent": BROWSER_USER_AGENT,
                    "Accept": "application/json, text/plain, */*",
                    "Origin": "https://fixr.co",
                    "Referer": "https://fixr.co/",
                    "Accept-Language": "en-GB,en;q=0.9",
                },
                method="GET",
            )
            try:
                with urlopen(request, timeout=self._timeout_seconds) as response:
                    raw = response.read()
            except HTTPError as error:
                if error.code in {502, 503, 504} and attempt + 1 < self._network_retries:
                    last_error = error
                    self._retry_sleep(2**attempt)
                    continue
                retry_after = _parse_retry_after(error.headers)
                raise FixrHttpError(
                    f"FIXR returned HTTP {error.code} for {path}",
                    status_code=error.code,
                    retry_after=retry_after,
                ) from error
            except (URLError, TimeoutError) as error:
                last_error = error
                if attempt + 1 < self._network_retries:
                    self._retry_sleep(2**attempt)
                    continue
                raise FixrError(f"FIXR request failed for {path}: {error}") from error

            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as error:
                raise FixrError(f"FIXR returned invalid JSON for {path}") from error
            if not isinstance(payload, dict):
                raise ValueError("FIXR payload must be an object")
            return payload

        raise FixrError(f"FIXR request failed for {path}: {last_error}") from last_error

    def _throttle(self) -> None:
        if self._min_interval_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self._min_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()


def _parse_event(payload: object, include_tickets: bool) -> EventSnapshot:
    if not isinstance(payload, dict):
        raise ValueError("FIXR payload must be an object")
    if "id" not in payload:
        raise ValueError("FIXR event payload missing required field: id")
    event_id = int(payload["id"])
    routing = str(payload.get("routing_part") or f"event-tickets-{event_id}")
    share_url = str(payload.get("share_url") or f"https://fixr.co/event/{routing}")
    label = payload.get("label")
    label_text = label.get("text") if isinstance(label, dict) else None
    tickets: tuple[TicketSnapshot, ...] = ()
    if include_tickets:
        raw_tickets = payload.get("tickets") or []
        if not isinstance(raw_tickets, list):
            raise ValueError("FIXR payload ticket list is invalid")
        tickets = tuple(_parse_ticket(item) for item in raw_tickets)
    organiser = payload.get("sales_account")
    organiser_id = None
    if isinstance(organiser, dict) and organiser.get("id") is not None:
        organiser_id = int(organiser["id"])
    return EventSnapshot(
        id=event_id,
        name=str(payload.get("name") or f"Event {event_id}"),
        share_url=share_url,
        tickets_url=f"{share_url.rstrip('/')}/tickets",
        label=str(label_text) if label_text else None,
        sold_out=bool(payload.get("sold_out")),
        tickets=tickets,
        organiser_id=organiser_id,
    )


def _parse_ticket(payload: object) -> TicketSnapshot:
    if not isinstance(payload, dict):
        raise ValueError("ticket payload must be an object")
    if "id" not in payload:
        raise ValueError("FIXR ticket payload missing required field: id")
    charges = payload.get("charges")
    total = charges.get("total") if isinstance(charges, dict) else None
    price = total.get("amount") if isinstance(total, dict) else None
    return TicketSnapshot(
        id=int(payload["id"]),
        name=str(payload.get("name") or f"Ticket {payload.get('id')}"),
        availability=classify_ticket(payload),
        price=str(price) if price is not None else None,
    )


def _parse_retry_after(
    headers: Message | dict[str, str] | None,
    _now: datetime.datetime | None = None,
) -> float | None:
    if headers is None:
        return None
    raw = headers.get("Retry-After") if hasattr(headers, "get") else None
    if raw is None:
        return None
    # Try numeric seconds first (most common).
    try:
        return float(raw)
    except (TypeError, ValueError):
        pass
    # Fall back to HTTP-date format per RFC 7231.
    try:
        dt = parsedate_to_datetime(raw)
        now = _now or datetime.datetime.now(tz=datetime.timezone.utc)
        return max(0.0, (dt - now).total_seconds())
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
