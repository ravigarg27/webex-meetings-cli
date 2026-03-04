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
