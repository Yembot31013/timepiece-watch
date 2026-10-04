from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from timepiece_watch.telegram import TelegramError, TelegramSettings, send_message


def _telegram_response(payload: dict, status: int = 200) -> MagicMock:
    body = json.dumps(payload).encode("utf-8")
    response = MagicMock()
    response.status = status
    response.read.return_value = body
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def test_send_message_posts_json_to_bot_api() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="99")
    with patch(
        "timepiece_watch.telegram.urlopen",
        return_value=_telegram_response({"ok": True, "result": {}}),
    ) as urlopen:
        send_message(settings, "[ON SALE] VK FEST 26")

    request = urlopen.call_args.args[0]
    assert request.full_url == "https://api.telegram.org/bot123:abc/sendMessage"
    body = json.loads(request.data.decode("utf-8"))
    assert body["chat_id"] == "99"
    assert body["text"] == "[ON SALE] VK FEST 26"
    assert body["disable_web_page_preview"] is False
    assert body["parse_mode"] == "HTML"


def _http_error(code: int, payload: dict | bytes, reason: str = "Bad Request") -> HTTPError:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    return HTTPError(
        url="https://api.telegram.org/bot123:abc/sendMessage",
        code=code,
        msg=reason,
        hdrs={},  # type: ignore[arg-type]
        fp=BytesIO(body),
    )


def test_send_message_raises_on_http_error() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="99")
    error = _http_error(401, {"ok": False, "description": "Unauthorized"}, "Unauthorized")
    with patch("timepiece_watch.telegram.urlopen", side_effect=error):
        with pytest.raises(TelegramError, match="HTTP 401: Unauthorized"):
            send_message(settings, "hello")


def test_send_message_follows_supergroup_migration() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="-111")
    migrated = _http_error(
        400,
        {
            "ok": False,
            "description": "Bad Request: group chat was upgraded to a supergroup chat",
            "parameters": {"migrate_to_chat_id": -100222},
        },
    )
    with patch(
        "timepiece_watch.telegram.urlopen",
        side_effect=[migrated, _telegram_response({"ok": True, "result": {}})],
    ) as urlopen:
        chat_id = send_message(settings, "<b>On sale</b>", retry_sleep=lambda _seconds: None)

    assert chat_id == "-100222"
    first = json.loads(urlopen.call_args_list[0].args[0].data.decode("utf-8"))
    second = json.loads(urlopen.call_args_list[1].args[0].data.decode("utf-8"))
    assert first["chat_id"] == "-111"
    assert second["chat_id"] == "-100222"
    assert urlopen.call_count == 2


def test_send_message_retries_html_parse_error_as_plain_text() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="99")
    parse_error = _http_error(
        400,
        {"ok": False, "description": "Bad Request: can't parse entities: unsupported start tag"},
    )
    with patch(
        "timepiece_watch.telegram.urlopen",
        side_effect=[parse_error, _telegram_response({"ok": True, "result": {}})],
    ) as urlopen:
        chat_id = send_message(settings, "<b>On sale</b>", retry_sleep=lambda _seconds: None)

    assert chat_id == "99"
    first = json.loads(urlopen.call_args_list[0].args[0].data.decode("utf-8"))
    second = json.loads(urlopen.call_args_list[1].args[0].data.decode("utf-8"))
    assert first["parse_mode"] == "HTML"
    assert "parse_mode" not in second
    assert second["text"] == "On sale"


def test_send_message_retries_too_many_requests() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="99")
    busy = _http_error(
        429,
        {
            "ok": False,
            "description": "Too Many Requests: retry after 12",
            "parameters": {"retry_after": 12},
        },
        "Too Many Requests",
    )
    slept: list[float] = []
    with patch(
        "timepiece_watch.telegram.urlopen",
        side_effect=[busy, _telegram_response({"ok": True, "result": {}})],
    ) as urlopen:
        send_message(settings, "hello", retry_sleep=slept.append)

    assert urlopen.call_count == 2
    assert slept == [12]


def test_send_message_uses_retry_after_header() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="99")
    busy = HTTPError(
        url="https://api.telegram.org/bot123:abc/sendMessage",
        code=429,
        msg="Too Many Requests",
        hdrs={"Retry-After": "4"},  # type: ignore[arg-type]
        fp=BytesIO(b"not-json"),
    )
    slept: list[float] = []
    with patch(
        "timepiece_watch.telegram.urlopen",
        side_effect=[busy, _telegram_response({"ok": True, "result": {}})],
    ):
        send_message(settings, "hello", retry_sleep=slept.append)
    assert slept == [4]


def test_send_message_includes_raw_body_when_error_json_is_invalid() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="99")
    error = _http_error(400, b"plain failure")
    with patch("timepiece_watch.telegram.urlopen", side_effect=error):
        with pytest.raises(TelegramError, match="HTTP 400: plain failure"):
            send_message(settings, "hello", retry_sleep=lambda _seconds: None)


def test_send_message_permanent_400_does_not_retry() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="99")
    error = _http_error(400, {"ok": False, "description": "Bad Request: chat not found"})
    with patch("timepiece_watch.telegram.urlopen", side_effect=error) as urlopen:
        with pytest.raises(TelegramError, match="HTTP 400: Bad Request: chat not found"):
            send_message(settings, "hello", retry_sleep=lambda _seconds: None)
    assert urlopen.call_count == 1


def test_send_message_raises_when_telegram_rejects_payload() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="99")
    with patch(
        "timepiece_watch.telegram.urlopen",
        return_value=_telegram_response({"ok": False, "description": "chat not found"}),
    ):
        with pytest.raises(TelegramError, match="chat not found"):
            send_message(settings, "hello")


def test_send_message_raises_on_network_failure() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="99")
    with patch("timepiece_watch.telegram.urlopen", side_effect=URLError("timed out")) as urlopen:
        with pytest.raises(TelegramError, match="request failed"):
            send_message(settings, "hello", retry_sleep=lambda _seconds: None)
    assert urlopen.call_count == 3


def test_send_message_dns_blip_recovers_on_retry() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="99")
    with patch(
        "timepiece_watch.telegram.urlopen",
        side_effect=[
            URLError("[Errno -3] Temporary failure in name resolution"),
            _telegram_response({"ok": True, "result": {}}),
        ],
    ) as urlopen:
        send_message(settings, "hello", retry_sleep=lambda _seconds: None)
    assert urlopen.call_count == 2


def test_send_message_skips_blank_text() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="99")
    with patch("timepiece_watch.telegram.urlopen") as urlopen:
        send_message(settings, "   ")
    urlopen.assert_not_called()


def test_send_message_raises_on_invalid_json() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="99")
    response = MagicMock()
    response.read.return_value = b"not-json"
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    with patch("timepiece_watch.telegram.urlopen", return_value=response):
        with pytest.raises(TelegramError, match="invalid JSON"):
            send_message(settings, "hello")


def test_send_message_gateway_error_retries_then_succeeds() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="99")
    gateway_error = HTTPError(
        url="https://api.telegram.org/bot123:abc/sendMessage",
        code=502,
        msg="Bad Gateway",
        hdrs={},  # type: ignore[arg-type]
        fp=BytesIO(b""),
    )
    with patch(
        "timepiece_watch.telegram.urlopen",
        side_effect=[gateway_error, _telegram_response({"ok": True, "result": {}})],
    ) as urlopen:
        send_message(settings, "hello", retry_sleep=lambda _seconds: None)
    assert urlopen.call_count == 2


def test_send_message_gateway_error_exhausted_raises() -> None:
    settings = TelegramSettings(bot_token="123:abc", chat_id="99")
    gateway_error = HTTPError(
        url="https://api.telegram.org/bot123:abc/sendMessage",
        code=503,
        msg="Service Unavailable",
        hdrs={},  # type: ignore[arg-type]
        fp=BytesIO(b""),
    )
    with patch("timepiece_watch.telegram.urlopen", side_effect=gateway_error) as urlopen:
        with pytest.raises(TelegramError, match="HTTP 503"):
            send_message(settings, "hello", retry_sleep=lambda _seconds: None)
    assert urlopen.call_count == 3
