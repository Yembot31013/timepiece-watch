from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from timepiece_watch.client import FixrClient, FixrError, FixrHttpError
from timepiece_watch.models import TicketAvailability


def _response(payload: object, status: int = 200) -> MagicMock:
    body = json.dumps(payload).encode("utf-8")
    response = MagicMock()
    response.status = status
    response.read.return_value = body
    response.headers = {}
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def test_fetch_event_maps_checkout_flags() -> None:
    payload = {
        "id": 350258228,
        "name": "VK FEST 26",
        "sold_out": False,
        "share_url": "https://fixr.co/event/vk-fest-26-tickets-350258228",
        "routing_part": "vk-fest-26-tickets-350258228",
        "label": {"text": "Just added"},
        "sales_account": {"id": 5486166, "name": "Timepiece"},
        "tickets": [
            {
                "id": 11,
                "name": "Entry 8-8:30pm",
                "sold_out": False,
                "not_yet_valid": True,
                "expired": False,
                "charges": {"total": {"amount": "4.00"}},
            }
        ],
    }
    client = FixrClient()
    with patch("timepiece_watch.client.urlopen", return_value=_response(payload)) as urlopen:
        event = client.fetch_event(350258228)

    request = urlopen.call_args.args[0]
    assert request.get_header("User-agent").startswith("Mozilla/5.0")
    assert "Chrome/" in request.get_header("User-agent")
    assert "_ts=" in request.full_url
    assert event.tickets[0].availability == TicketAvailability.COMING_SOON
    assert event.tickets[0].price == "4.00"
    assert event.tickets_url.endswith("/tickets")
    assert event.organiser_id == 5486166


def test_http_error_captures_retry_after() -> None:
    http_error = HTTPError(
        url="https://api.fixr.co/x",
        code=429,
        msg="Too Many Requests",
        hdrs={"Retry-After": "30"},  # type: ignore[arg-type]
        fp=BytesIO(b"slow down"),
    )
    client = FixrClient()
    with patch("timepiece_watch.client.urlopen", side_effect=http_error):
        with pytest.raises(FixrHttpError) as exc_info:
            client.fetch_venue(2783)

    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after == 30.0


def test_network_failure_retries_then_fails() -> None:
    client = FixrClient(retry_sleep=lambda _seconds: None)
    with patch("timepiece_watch.client.urlopen", side_effect=URLError("timed out")) as urlopen:
        with pytest.raises(FixrError, match="request failed"):
            client.fetch_event(1)
    assert urlopen.call_count == 3


def test_timeout_retries_then_fails() -> None:
    client = FixrClient(retry_sleep=lambda _seconds: None)
    with patch("timepiece_watch.client.urlopen", side_effect=TimeoutError("timed out")) as urlopen:
        with pytest.raises(FixrError, match="request failed"):
            client.fetch_venue(2783)
    assert urlopen.call_count == 3


def test_dns_blip_recovers_on_retry() -> None:
    payload = {"id": 2783, "name": "Timepiece Nightclub", "events": []}
    client = FixrClient(retry_sleep=lambda _seconds: None)
    with patch(
        "timepiece_watch.client.urlopen",
        side_effect=[
            URLError("[Errno -3] Temporary failure in name resolution"),
            _response(payload),
        ],
    ) as urlopen:
        events = client.fetch_venue(2783)
    assert events == ()
    assert urlopen.call_count == 2


def test_client_throttles_between_requests() -> None:
    import time

    client = FixrClient(min_interval_seconds=0.05)
    with patch("timepiece_watch.client.urlopen", return_value=_response({"id": 2783, "events": []})):
        started = time.monotonic()
        client.fetch_venue(2783)
        client.fetch_venue(2783)
        assert time.monotonic() - started >= 0.05


def test_bare_non_object_payload_is_rejected() -> None:
    client = FixrClient()
    with patch("timepiece_watch.client.urlopen", return_value=_response([1, 2, 3])):
        with pytest.raises(ValueError, match="FIXR payload"):
            client.fetch_venue(2783)


def test_invalid_json_becomes_fixr_error() -> None:
    response = MagicMock()
    response.read.return_value = b"not-json"
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    client = FixrClient()
    with patch("timepiece_watch.client.urlopen", return_value=response):
        with pytest.raises(FixrError, match="invalid JSON"):
            client.fetch_event(1)


def test_venue_payload_requires_event_list() -> None:
    client = FixrClient()
    with patch("timepiece_watch.client.urlopen", return_value=_response({"id": 2783, "name": "Timepiece"})):
        with pytest.raises(ValueError, match="event list"):
            client.fetch_venue(2783)


def test_event_payload_missing_id_raises_value_error() -> None:
    client = FixrClient()
    with patch("timepiece_watch.client.urlopen", return_value=_response({"name": "No ID"})):
        with pytest.raises(ValueError, match="missing required field: id"):
            client.fetch_event(1)


def test_retry_after_http_date_is_parsed() -> None:
    import datetime
    from timepiece_watch.client import _parse_retry_after

    future = datetime.datetime(2026, 9, 18, 18, 0, 0, tzinfo=datetime.timezone.utc)
    now = datetime.datetime(2026, 9, 18, 17, 0, 0, tzinfo=datetime.timezone.utc)
    headers = {"Retry-After": future.strftime("%a, %d %b %Y %H:%M:%S GMT")}
    assert _parse_retry_after(headers, _now=now) == 3600.0


def test_retry_after_unparseable_returns_none() -> None:
    from timepiece_watch.client import _parse_retry_after

    assert _parse_retry_after({"Retry-After": "not-a-date"}) is None


def test_ticket_payload_missing_id_raises_value_error() -> None:
    payload = {
        "id": 999,
        "name": "Event",
        "sold_out": False,
        "tickets": [{"name": "No ID ticket", "sold_out": False, "expired": False, "not_yet_valid": False}],
    }
    client = FixrClient()
    with patch("timepiece_watch.client.urlopen", return_value=_response(payload)):
        with pytest.raises(ValueError, match="missing required field: id"):
            client.fetch_event(999)


def test_gateway_error_retries_then_succeeds() -> None:
    payload = {"id": 1, "name": "Event", "sold_out": False, "tickets": []}
    gateway_error = HTTPError(
        url="https://api.fixr.co/api/v2/app/event/1",
        code=502,
        msg="Bad Gateway",
        hdrs={},  # type: ignore[arg-type]
        fp=BytesIO(b""),
    )
    client = FixrClient(retry_sleep=lambda _seconds: None)
    with patch(
        "timepiece_watch.client.urlopen",
        side_effect=[gateway_error, _response(payload)],
    ) as urlopen:
        event = client.fetch_event(1)
    assert event.id == 1
    assert urlopen.call_count == 2


def test_gateway_error_exhausted_raises_http_error() -> None:
    gateway_error = HTTPError(
        url="https://api.fixr.co/api/v2/app/event/1",
        code=503,
        msg="Service Unavailable",
        hdrs={},  # type: ignore[arg-type]
        fp=BytesIO(b""),
    )
    client = FixrClient(retry_sleep=lambda _seconds: None)
    with patch("timepiece_watch.client.urlopen", side_effect=gateway_error) as urlopen:
        with pytest.raises(FixrHttpError) as exc_info:
            client.fetch_event(1)
    assert exc_info.value.status_code == 503
    assert urlopen.call_count == 3
