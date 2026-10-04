from unittest.mock import MagicMock, patch
import urllib.error

from timepiece_watch.webhook import WebhookSettings, send_automation_webhook


def test_send_automation_webhook_success() -> None:
    settings = WebhookSettings(url="https://example.com/api/webhooks/trigger", secret="test_secret")

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        success = send_automation_webhook(
            settings=settings,
            event_id=12345,
            action="reserve",
            platform="fixr",
            tickets_url="https://fixr.co/event/12345",
            ticket_ids=[1, 2],
        )

        assert success is True
        assert mock_urlopen.call_count == 1
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("X-timepiece-signature") == "test_secret"


def test_send_automation_webhook_handles_network_error() -> None:
    settings = WebhookSettings(url="https://example.com/api/webhooks/trigger")

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        success = send_automation_webhook(
            settings=settings,
            event_id=12345,
        )
        assert success is False
