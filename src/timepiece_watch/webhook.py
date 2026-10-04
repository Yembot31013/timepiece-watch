from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WebhookSettings:
    url: str
    secret: str | None = None
    timeout: float = 10.0


def send_automation_webhook(
    settings: WebhookSettings,
    event_id: int | str,
    action: str = "reserve",
    platform: str = "fixr",
    tickets_url: str | None = None,
    ticket_ids: list[int] | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Send an immediate trigger webhook to the browser automation platform."""
    payload = {
        "eventId": event_id,
        "action": action,
        "platform": platform,
        "ticketsUrl": tickets_url,
        "ticketIds": ticket_ids or [],
        "secret": settings.secret,
        "metadata": metadata or {},
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=settings.url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "timepiece-watch/0.1.0",
            **({"x-timepiece-signature": settings.secret} if settings.secret else {}),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=settings.timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
