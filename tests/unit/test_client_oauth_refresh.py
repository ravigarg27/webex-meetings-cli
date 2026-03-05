import httpx

from webex_cli.client.api import WebexApiClient


class _FakeHttpClient:
    def __init__(self) -> None:
        self.calls = 0
        self.auth_headers: list[str | None] = []

    def request(self, method, url, headers=None, params=None, timeout=None):  # noqa: ANN001
        self.calls += 1
        self.auth_headers.append((headers or {}).get("Authorization"))
        request = httpx.Request(method, url)
        if self.calls == 1:
            return httpx.Response(401, request=request, json={"message": "unauthorized"})
        return httpx.Response(200, request=request, json={"result": "ok"})

    def close(self) -> None:
        return None


def test_client_retries_once_after_401_using_refresh_callback() -> None:
    refreshed_tokens: list[str] = []

    def _refresh_token() -> str:
        refreshed_tokens.append("new-token")
        return "new-token"

    client = WebexApiClient(
        base_url="https://webexapis.com",
        token="old-token",
        retry_attempts=1,
        refresh_token_callback=_refresh_token,
    )
    fake_http = _FakeHttpClient()
    client._client = fake_http

    payload = client._request_json("GET", "/v1/test")

    assert payload["result"] == "ok"
    assert refreshed_tokens == ["new-token"]
    assert fake_http.auth_headers == ["Bearer old-token", "Bearer new-token"]


def test_client_create_meeting_translates_template_id_field(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(self, method, path, *, params=None, json_body=None, timeout_seconds=None, extra_headers=None):  # noqa: ANN001
        captured["method"] = method
        captured["path"] = path
        captured["json_body"] = json_body
        captured["extra_headers"] = extra_headers
        return {"ok": True}

    monkeypatch.setattr(WebexApiClient, "_request_json", _fake_request_json)
    client = WebexApiClient(base_url="https://webexapis.com", token="token")
    client.create_meeting({"title": "Team Sync", "template_id": "tpl-1"}, idempotency_key="idem-1")

    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/meetings"
    assert captured["json_body"] == {"title": "Team Sync", "templateId": "tpl-1"}
    assert captured["extra_headers"] == {"Idempotency-Key": "idem-1"}


def test_client_update_recurrence_translates_from_occurrence_field(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(self, method, path, *, params=None, json_body=None, timeout_seconds=None, extra_headers=None):  # noqa: ANN001
        captured["method"] = method
        captured["path"] = path
        captured["json_body"] = json_body
        captured["extra_headers"] = extra_headers
        return {"ok": True}

    monkeypatch.setattr(WebexApiClient, "_request_json", _fake_request_json)
    client = WebexApiClient(base_url="https://webexapis.com", token="token")
    client.update_recurrence("series-1", {"rrule": "FREQ=WEEKLY", "from_occurrence": "2026-01-10T10:00:00Z"}, idempotency_key="idem-1")

    assert captured["method"] == "PATCH"
    assert captured["path"] == "/v1/meetingSeries/series-1"
    assert captured["json_body"] == {"rrule": "FREQ=WEEKLY", "fromOccurrence": "2026-01-10T10:00:00Z"}
    assert captured["extra_headers"] == {"Idempotency-Key": "idem-1"}
