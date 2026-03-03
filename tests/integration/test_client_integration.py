import httpx
import pytest

from webex_cli.client.api import WebexApiClient
from webex_cli.errors import CliError, DomainCode


def test_client_retries_on_429(monkeypatch) -> None:
    monkeypatch.setattr("webex_cli.client.api.time.sleep", lambda _: None)
    request = httpx.Request("GET", "https://webexapis.com/v1/people/me")
    responses = [
        httpx.Response(429, request=request, json={"message": "rate limited"}, headers={"Retry-After": "0"}),
        httpx.Response(200, request=request, json={"id": "u1", "displayName": "User", "emails": ["u@example.test"]}),
    ]

    def fake_request(self, method, url, headers=None, params=None):
        return responses.pop(0)

    monkeypatch.setattr(httpx.Client, "request", fake_request, raising=True)
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=2)
    data = client.whoami()
    assert data["user_id"] == "u1"
    assert len(responses) == 0


def test_client_maps_403_to_no_access(monkeypatch) -> None:
    request = httpx.Request("GET", "https://webexapis.com/v1/recordings/r1")

    def fake_request(self, method, url, headers=None, params=None):
        return httpx.Response(403, request=request, json={"code": "FORBIDDEN"})

    monkeypatch.setattr(httpx.Client, "request", fake_request, raising=True)
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=1)
    with pytest.raises(CliError) as exc:
        client.get_recording("r1")
    assert exc.value.code == DomainCode.NO_ACCESS


def test_client_meeting_page_shape(monkeypatch) -> None:
    request = httpx.Request("GET", "https://webexapis.com/v1/meetings")

    def fake_request(self, method, url, headers=None, params=None):
        return httpx.Response(200, request=request, json={"items": [{"id": "m1"}], "nextPageToken": "abc"})

    monkeypatch.setattr(httpx.Client, "request", fake_request, raising=True)
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=1)
    items, token = client.list_meetings(
        from_utc="2026-01-01T00:00:00Z",
        to_utc="2026-01-02T00:00:00Z",
        participant="me",
        page_size=50,
        page_token=None,
    )
    assert items == [{"id": "m1"}]
    assert token == "abc"

