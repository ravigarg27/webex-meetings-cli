from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import random
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from webex_cli.errors import CliError, DomainCode


def _normalize_error_code(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except Exception:
        return None
    code = payload.get("code") or payload.get("errorCode")
    if not code:
        return None
    return str(code).strip().upper()


@dataclass(slots=True)
class WebexApiClient:
    base_url: str
    token: str
    timeout_seconds: int = 30
    download_timeout_seconds: int = 300
    retry_attempts: int = 5
    max_delay_seconds: float = 8.0
    _client: httpx.Client | None = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _build_url(self, path: str) -> str:
        return urljoin(f"{self.base_url.rstrip('/')}/", path.lstrip("/"))

    @staticmethod
    def _encoded(value: str) -> str:
        return quote(value, safe="")

    def _map_response_error(self, response: httpx.Response, path: str | None = None) -> CliError:
        status = response.status_code
        details: dict[str, Any] = {"status_code": status}
        code = _normalize_error_code(response)
        if code:
            details["upstream_code"] = code

        if status == 401:
            return CliError(DomainCode.AUTH_INVALID, "Authentication failed.", details=details)
        if status == 403 and code in {"FEATURE_DISABLED", "ORG_POLICY_RESTRICTED"}:
            normalized_path = (path or "").lower()
            if "meetingtranscripts" in normalized_path:
                return CliError(
                    DomainCode.TRANSCRIPT_DISABLED,
                    "Transcript feature is disabled by policy.",
                    details=details,
                )
            if "/recordings" in normalized_path:
                return CliError(
                    DomainCode.RECORDING_DISABLED,
                    "Recording feature is disabled by policy.",
                    details=details,
                )
            return CliError(
                DomainCode.NO_ACCESS,
                "Access blocked by org policy.",
                details=details,
            )
        if status == 403:
            return CliError(DomainCode.NO_ACCESS, "Access denied.", details=details)
        if status == 404:
            return CliError(DomainCode.NOT_FOUND, "Resource not found.", details=details)
        if status == 429:
            return CliError(DomainCode.RATE_LIMITED, "Rate limited by upstream.", details=details)
        if status >= 500:
            return CliError(
                DomainCode.UPSTREAM_UNAVAILABLE,
                "Upstream service unavailable.",
                details=details,
            )
        return CliError(
            DomainCode.VALIDATION_ERROR,
            "Request rejected by upstream.",
            details=details,
        )

    def _get_client(self, timeout: int) -> httpx.Client:
        # Keep one shared client for connection pooling.
        if self._client is None:
            self._client = httpx.Client()
        return self._client

    @staticmethod
    def _retry_after_delay(response: httpx.Response) -> float | None:
        retry_after = response.headers.get("Retry-After")
        if not retry_after:
            return None
        if retry_after.isdigit():
            return float(retry_after)
        try:
            dt = parsedate_to_datetime(retry_after)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            seconds = (dt - datetime.now(timezone.utc)).total_seconds()
            return max(0.0, seconds)
        except Exception:
            return None

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
    ) -> httpx.Response:
        timeout = timeout_seconds or self.timeout_seconds
        delay = 0.5
        last_error: CliError | None = None
        for attempt in range(self.retry_attempts):
            try:
                client = self._get_client(timeout=timeout)
                response = client.request(
                    method=method,
                    url=self._build_url(path),
                    headers=self._headers(),
                    params=params,
                    timeout=timeout,
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.NetworkError) as exc:
                last_error = CliError(
                    DomainCode.UPSTREAM_UNAVAILABLE,
                    "Network error while calling upstream.",
                    details={"exception": str(exc)},
                )
                if attempt == self.retry_attempts - 1:
                    raise last_error from exc
                # Exponential backoff with full jitter.
                wait = random.uniform(0, min(delay, self.max_delay_seconds))
                time.sleep(wait)
                delay *= 2
                continue

            if response.status_code in {429} or response.status_code >= 500:
                last_error = self._map_response_error(response, path=path)
                if attempt == self.retry_attempts - 1:
                    raise last_error
                retry_after_delay = self._retry_after_delay(response)
                if retry_after_delay is not None:
                    time.sleep(min(retry_after_delay, self.max_delay_seconds))
                else:
                    wait = random.uniform(0, min(delay, self.max_delay_seconds))
                    time.sleep(wait)
                delay *= 2
                continue

            if response.is_error:
                raise self._map_response_error(response, path=path)

            return response

        if last_error:
            raise last_error
        raise CliError(DomainCode.INTERNAL_ERROR, "Retry loop ended unexpectedly.")

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        response = self._request(method, path, params=params, timeout_seconds=timeout_seconds)
        if response.content.strip() == b"":
            return {}
        try:
            return response.json()
        except Exception as exc:
            raise CliError(
                DomainCode.UPSTREAM_UNAVAILABLE,
                "Upstream returned invalid JSON.",
                details={"path": path},
            ) from exc

    def _request_bytes(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> bytes:
        response = self._request(
            method,
            path,
            params=params,
            timeout_seconds=self.download_timeout_seconds,
        )
        return response.content

    def whoami(self) -> dict[str, Any]:
        payload = self._request_json("GET", "/v1/people/me")
        emails = payload.get("emails") or []
        return {
            "user_id": payload.get("id"),
            "display_name": payload.get("displayName") or payload.get("display_name"),
            "primary_email": emails[0] if emails else None,
            "org_id": payload.get("orgId") or payload.get("org_id"),
            "site_url": payload.get("siteUrl") or payload.get("site_url"),
            "token_state": "valid",
            "raw": payload,
        }

    def probe_meetings_access(self) -> None:
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=1)).isoformat()
        end = now.isoformat()
        self._request_json(
            "GET",
            "/v1/meetings",
            params={"from": start, "to": end, "max": 1},
        )

    @staticmethod
    def _normalize_page(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        items = payload.get("items") or payload.get("meetings") or payload.get("recordings") or []
        next_token = payload.get("next_page_token") or payload.get("nextPageToken") or payload.get("next")
        return items, next_token

    def list_meetings(
        self,
        *,
        from_utc: str,
        to_utc: str,
        participant: str,
        page_size: int,
        page_token: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        params: dict[str, Any] = {"from": from_utc, "to": to_utc, "max": page_size, "participant": participant}
        if page_token:
            params["pageToken"] = page_token
        payload = self._request_json("GET", "/v1/meetings", params=params)
        return self._normalize_page(payload)

    def get_meeting(self, meeting_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/v1/meetings/{self._encoded(meeting_id)}")

    def get_meeting_join_url(self, meeting_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/v1/meetings/{self._encoded(meeting_id)}")

    def get_transcript_status(self, meeting_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/v1/meetingTranscripts/{self._encoded(meeting_id)}")

    def get_transcript(self, meeting_id: str, format_value: str) -> dict[str, Any]:
        return self._request_json(
            "GET",
            f"/v1/meetingTranscripts/{self._encoded(meeting_id)}",
            params={"format": format_value},
            timeout_seconds=self.download_timeout_seconds,
        )

    def list_recordings(
        self,
        *,
        from_utc: str,
        to_utc: str,
        participant: str,
        page_size: int,
        page_token: str | None,
        meeting_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        params: dict[str, Any] = {"from": from_utc, "to": to_utc, "max": page_size, "participant": participant}
        if page_token:
            params["pageToken"] = page_token
        if meeting_id:
            params["meetingId"] = meeting_id
        payload = self._request_json("GET", "/v1/recordings", params=params)
        return self._normalize_page(payload)

    def get_recording(self, recording_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/v1/recordings/{self._encoded(recording_id)}")

    def list_recordings_for_meeting(self, meeting_id: str) -> list[dict[str, Any]]:
        payload = self._request_json(
            "GET",
            "/v1/recordings",
            params={"meetingId": meeting_id, "max": 200},
        )
        items, _ = self._normalize_page(payload)
        return items

    def download_recording(self, recording_id: str, quality: str) -> tuple[bytes, str]:
        metadata = self.get_recording(recording_id)
        download_url = (
            metadata.get("downloadUrl")
            or metadata.get("download_url")
            or metadata.get("temporaryDirectDownloadLinks", {}).get(quality)
        )
        if not download_url:
            raise CliError(
                DomainCode.NOT_FOUND,
                "Recording download URL not available.",
                details={"recording_id": recording_id},
            )
        with httpx.Client(timeout=self.download_timeout_seconds) as client:
            response = client.get(download_url, headers=self._headers())
        if response.is_error:
            raise self._map_response_error(response, path="/v1/recordings/download")
        actual_quality = metadata.get("quality") or quality
        return response.content, str(actual_quality)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
