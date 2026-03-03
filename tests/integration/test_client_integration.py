import httpx
import pytest
import respx

from webex_cli.client.api import WebexApiClient
from webex_cli.errors import CliError, DomainCode


@respx.mock
def test_client_retries_on_429(monkeypatch) -> None:
    monkeypatch.setattr("webex_cli.client.api.time.sleep", lambda _: None)
    route = respx.get("https://webexapis.com/v1/people/me").mock(
        side_effect=[
            httpx.Response(429, json={"message": "rate limited"}, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"id": "u1", "displayName": "User", "emails": ["u@example.test"]}),
        ]
    )
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=2)
    data = client.whoami()
    assert data["user_id"] == "u1"
    assert route.call_count == 2


@respx.mock
def test_client_maps_403_to_no_access() -> None:
    respx.get("https://webexapis.com/v1/recordings/r1").mock(
        return_value=httpx.Response(403, json={"code": "FORBIDDEN"})
    )
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=1)
    with pytest.raises(CliError) as exc:
        client.get_recording("r1")
    assert exc.value.code == DomainCode.NO_ACCESS


@respx.mock
def test_client_meeting_page_shape() -> None:
    respx.get("https://webexapis.com/v1/meetings").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": "m1"}], "nextPageToken": "abc"},
        )
    )
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

