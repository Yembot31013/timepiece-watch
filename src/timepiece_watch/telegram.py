from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TELEGRAM_API_ROOT = "https://api.telegram.org"
_RETRYABLE_HTTP = frozenset({408, 429, 500, 502, 503, 504})


class TelegramError(Exception):
    """Raised when a Telegram send fails."""


@dataclass(frozen=True)
class TelegramSettings:
    bot_token: str
    chat_id: str


@dataclass(frozen=True)
class _HttpDetail:
    description: str
    migrate_to_chat_id: str | None = None
    retry_after: float | None = None


def send_message(
    settings: TelegramSettings,
    text: str,
    timeout_seconds: float = 20.0,
    network_retries: int = 3,
    retry_sleep: Callable[[float], None] = time.sleep,
) -> str:
    if not text.strip():
        return settings.chat_id
    chat_id = settings.chat_id
    parse_mode: str | None = "HTML"
    message_text = text
    used_migration = False
    used_plain_text = False
    transient_attempt = 0
    attempts = max(1, network_retries)
    last_error: BaseException | None = None

    while True:
        request = _build_request(settings.bot_token, chat_id, message_text, parse_mode)
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read()
        except HTTPError as error:
            last_error = error
            detail = _http_detail(error)
            if detail.migrate_to_chat_id and not used_migration:
                used_migration = True
                chat_id = detail.migrate_to_chat_id
                continue
            if parse_mode is not None and _is_parse_error(detail.description) and not used_plain_text:
                used_plain_text = True
                parse_mode = None
                message_text = strip_html(text)
                continue
            if error.code in _RETRYABLE_HTTP and transient_attempt + 1 < attempts:
                transient_attempt += 1
                retry_sleep(_retry_delay(detail.retry_after, transient_attempt))
                continue
            raise TelegramError(
                f"Telegram returned HTTP {error.code}: {detail.description}"
            ) from error
        except (URLError, TimeoutError) as error:
            last_error = error
            if transient_attempt + 1 < attempts:
                transient_attempt += 1
                retry_sleep(2 ** (transient_attempt - 1))
                continue
            raise TelegramError(f"Telegram request failed: {error}") from error

        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise TelegramError("Telegram returned invalid JSON") from error
        if not isinstance(body, dict) or not body.get("ok"):
            description = body.get("description") if isinstance(body, dict) else None
            raise TelegramError(description or "Telegram rejected the message")
        return chat_id

    raise TelegramError(f"Telegram request failed: {last_error}") from last_error


def strip_html(text: str) -> str:
    return (
        text.replace("<b>", "")
        .replace("</b>", "")
        .replace("<i>", "")
        .replace("</i>", "")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )


def _build_request(
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str | None,
) -> Request:
    payload: dict[str, object] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return Request(
        f"{TELEGRAM_API_ROOT}/bot{bot_token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )


def _http_detail(error: HTTPError) -> _HttpDetail:
    raw = b""
    try:
        raw = error.read() or b""
    except OSError:
        raw = b""
    description = str(error.reason or f"HTTP {error.code}")
    migrate_to_chat_id: str | None = None
    retry_after = _header_retry_after(error)
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        if raw:
            description = raw.decode("utf-8", errors="replace")[:200]
        return _HttpDetail(description=description, retry_after=retry_after)
    if isinstance(body, dict):
        if body.get("description"):
            description = str(body["description"])
        params = body.get("parameters")
        if isinstance(params, dict):
            if params.get("migrate_to_chat_id") is not None:
                migrate_to_chat_id = str(params["migrate_to_chat_id"])
            if params.get("retry_after") is not None:
                parsed = _as_positive_float(params.get("retry_after"))
                if parsed is not None:
                    retry_after = parsed
    return _HttpDetail(
        description=description,
        migrate_to_chat_id=migrate_to_chat_id,
        retry_after=retry_after,
    )


def _header_retry_after(error: HTTPError) -> float | None:
    if error.headers is None:
        return None
    return _as_positive_float(error.headers.get("Retry-After"))


def _as_positive_float(value: object) -> float | None:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _retry_delay(retry_after: float | None, transient_attempt: int) -> float:
    if retry_after is not None:
        return retry_after
    return 2 ** (transient_attempt - 1)


def _is_parse_error(description: str) -> bool:
    lowered = description.lower()
    return "can't parse entities" in lowered or "can't find end of the entity" in lowered
