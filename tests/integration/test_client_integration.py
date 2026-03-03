import httpx
import pytest
import socket

from webex_cli.client.api import WebexApiClient
from webex_cli.errors import CliError, DomainCode


def test_client_retries_on_429(monkeypatch) -> None:
    monkeypatch.setattr("webex_cli.client.api.time.sleep", lambda _: None)
    request = httpx.Request("GET", "https://webexapis.com/v1/people/me")
    responses = [
        httpx.Response(429, request=request, json={"message": "rate limited"}, headers={"Retry-After": "0"}),
        httpx.Response(200, request=request, json={"id": "u1", "displayName": "User", "emails": ["u@example.test"]}),
    ]

    seen_auth = []
    seen_params = []

    def fake_request(self, method, url, headers=None, params=None, timeout=None):
        seen_auth.append((headers or {}).get("Authorization"))
        seen_params.append(params)
        return responses.pop(0)

    monkeypatch.setattr(httpx.Client, "request", fake_request, raising=True)
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=2)
    data = client.whoami()
    assert data["user_id"] == "u1"
    assert len(responses) == 0
    assert seen_auth[0] == "Bearer token"
    assert seen_params[0] is None


def test_client_honors_retry_after_header(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("webex_cli.client.api.time.sleep", lambda s: sleeps.append(s))
    request = httpx.Request("GET", "https://webexapis.com/v1/people/me")
    responses = [
        httpx.Response(429, request=request, json={"message": "rate limited"}, headers={"Retry-After": "13"}),
        httpx.Response(200, request=request, json={"id": "u1", "displayName": "User", "emails": ["u@example.test"]}),
    ]

    def fake_request(self, method, url, headers=None, params=None, timeout=None):
        return responses.pop(0)

    monkeypatch.setattr(httpx.Client, "request", fake_request, raising=True)
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=2)
    client.whoami()
    assert sleeps == [13.0]


def test_client_maps_403_to_no_access(monkeypatch) -> None:
    request = httpx.Request("GET", "https://webexapis.com/v1/recordings/r1")

    def fake_request(self, method, url, headers=None, params=None, timeout=None):
        assert headers["Authorization"] == "Bearer token"
        return httpx.Response(403, request=request, json={"code": "FORBIDDEN"})

    monkeypatch.setattr(httpx.Client, "request", fake_request, raising=True)
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=1)
    with pytest.raises(CliError) as exc:
        client.get_recording("r1")
    assert exc.value.code == DomainCode.NO_ACCESS


def test_client_meeting_page_shape(monkeypatch) -> None:
    request = httpx.Request("GET", "https://webexapis.com/v1/meetings")

    def fake_request(self, method, url, headers=None, params=None, timeout=None):
        assert headers["Authorization"] == "Bearer token"
        assert params["participant"] == "me"
        assert params["max"] == 50
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


def test_client_rejects_unknown_page_payload_shape(monkeypatch) -> None:
    request = httpx.Request("GET", "https://webexapis.com/v1/meetings")

    def fake_request(self, method, url, headers=None, params=None, timeout=None):
        return httpx.Response(200, request=request, json={"unexpected": []})

    monkeypatch.setattr(httpx.Client, "request", fake_request, raising=True)
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=1)
    with pytest.raises(CliError) as exc:
        client.list_meetings(
            from_utc="2026-01-01T00:00:00Z",
            to_utc="2026-01-02T00:00:00Z",
            participant="me",
            page_size=50,
            page_token=None,
        )
    assert exc.value.code == DomainCode.UPSTREAM_UNAVAILABLE


def test_client_maps_transcript_disabled(monkeypatch) -> None:
    request = httpx.Request("GET", "https://webexapis.com/v1/meetingTranscripts/m1")

    def fake_request(self, method, url, headers=None, params=None, timeout=None):
        return httpx.Response(403, request=request, json={"code": "FEATURE_DISABLED"})

    monkeypatch.setattr(httpx.Client, "request", fake_request, raising=True)
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=1)
    with pytest.raises(CliError) as exc:
        client.get_transcript_status("m1")
    assert exc.value.code == DomainCode.TRANSCRIPT_DISABLED


def test_list_recordings_for_meeting_paginates(monkeypatch) -> None:
    request = httpx.Request("GET", "https://webexapis.com/v1/recordings")
    responses = [
        httpx.Response(200, request=request, json={"items": [{"id": "r1"}], "nextPageToken": "n1"}),
        httpx.Response(200, request=request, json={"items": [{"id": "r2"}]}),
    ]

    def fake_request(self, method, url, headers=None, params=None, timeout=None):
        return responses.pop(0)

    monkeypatch.setattr(httpx.Client, "request", fake_request, raising=True)
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=1)
    items = client.list_recordings_for_meeting("m1")
    assert [item["id"] for item in items] == ["r1", "r2"]


def test_download_recording_falls_back_to_available_quality(monkeypatch) -> None:
    request_meta = httpx.Request("GET", "https://webexapis.com/v1/recordings/r1")
    request_download = httpx.Request("GET", "https://download.example.test/high.mp4")
    responses = [
        httpx.Response(
            200,
            request=request_meta,
            json={"id": "r1", "temporaryDirectDownloadLinks": {"high": "https://download.example.test/high.mp4"}},
        ),
        httpx.Response(200, request=request_download, content=b"video-bytes"),
    ]
    seen_urls: list[str] = []

    def fake_request(self, method, url, headers=None, params=None, timeout=None):
        seen_urls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(httpx.Client, "request", fake_request, raising=True)
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=1)
    content, quality = client.download_recording("r1", "best")
    assert content == b"video-bytes"
    assert quality == "high"
    assert seen_urls == ["https://webexapis.com/v1/recordings/r1", "https://download.example.test/high.mp4"]


def test_download_recording_falls_back_from_high_to_best(monkeypatch) -> None:
    request_meta = httpx.Request("GET", "https://webexapis.com/v1/recordings/r1")
    request_download = httpx.Request("GET", "https://download.example.test/best.mp4")
    responses = [
        httpx.Response(
            200,
            request=request_meta,
            json={"id": "r1", "temporaryDirectDownloadLinks": {"best": "https://download.example.test/best.mp4"}},
        ),
        httpx.Response(200, request=request_download, content=b"video-bytes"),
    ]

    def fake_request(self, method, url, headers=None, params=None, timeout=None):
        return responses.pop(0)

    monkeypatch.setattr(httpx.Client, "request", fake_request, raising=True)
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=1)
    content, quality = client.download_recording("r1", "high")
    assert content == b"video-bytes"
    assert quality == "best"


def test_download_recording_retries_transient_download_failures(monkeypatch) -> None:
    monkeypatch.setattr("webex_cli.client.api.time.sleep", lambda _: None)
    request_meta = httpx.Request("GET", "https://webexapis.com/v1/recordings/r1")
    request_download = httpx.Request("GET", "https://download.example.test/file.mp4")
    responses = [
        httpx.Response(
            200,
            request=request_meta,
            json={"id": "r1", "downloadUrl": "https://download.example.test/file.mp4"},
        ),
        httpx.Response(503, request=request_download, json={"message": "temporary failure"}),
        httpx.Response(200, request=request_download, content=b"ok"),
    ]

    def fake_request(self, method, url, headers=None, params=None, timeout=None):
        return responses.pop(0)

    monkeypatch.setattr(httpx.Client, "request", fake_request, raising=True)
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=2)
    content, quality = client.download_recording("r1", "best")
    assert content == b"ok"
    assert quality == "best"


def test_download_recording_does_not_forward_auth_to_untrusted_host(monkeypatch) -> None:
    request_meta = httpx.Request("GET", "https://webexapis.com/v1/recordings/r1")
    request_download = httpx.Request("GET", "https://download.example.test/file.mp4")
    responses = [
        httpx.Response(200, request=request_meta, json={"id": "r1", "downloadUrl": "https://download.example.test/file.mp4"}),
        httpx.Response(200, request=request_download, content=b"ok"),
    ]
    seen_auth: list[str | None] = []

    def fake_request(self, method, url, headers=None, params=None, timeout=None):
        seen_auth.append((headers or {}).get("Authorization"))
        return responses.pop(0)

    monkeypatch.setattr(httpx.Client, "request", fake_request, raising=True)
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=1)
    content, quality = client.download_recording("r1", "best")
    assert content == b"ok"
    assert quality == "best"
    # metadata request uses auth; untrusted absolute download does not.
    assert seen_auth == ["Bearer token", None]


def test_download_recording_blocks_private_host(monkeypatch) -> None:
    request_meta = httpx.Request("GET", "https://webexapis.com/v1/recordings/r1")

    def fake_request(self, method, url, headers=None, params=None, timeout=None):
        return httpx.Response(200, request=request_meta, json={"id": "r1", "downloadUrl": "https://127.0.0.1/file.mp4"})

    monkeypatch.setattr(httpx.Client, "request", fake_request, raising=True)
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=1)
    with pytest.raises(CliError) as exc:
        client.download_recording("r1", "best")
    assert exc.value.code == DomainCode.VALIDATION_ERROR


def test_download_recording_blocks_host_resolving_to_private_ip(monkeypatch) -> None:
    request_meta = httpx.Request("GET", "https://webexapis.com/v1/recordings/r1")

    def fake_request(self, method, url, headers=None, params=None, timeout=None):
        return httpx.Response(
            200,
            request=request_meta,
            json={"id": "r1", "downloadUrl": "https://download.example.test/file.mp4"},
        )

    def fake_getaddrinfo(host, port, type=0, proto=0, flags=0):
        assert host == "download.example.test"
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
        ]

    monkeypatch.setattr(httpx.Client, "request", fake_request, raising=True)
    monkeypatch.setattr("webex_cli.client.api.socket.getaddrinfo", fake_getaddrinfo)
    client = WebexApiClient(base_url="https://webexapis.com", token="token", retry_attempts=1)
    with pytest.raises(CliError) as exc:
        client.download_recording("r1", "best")
    assert exc.value.code == DomainCode.VALIDATION_ERROR
