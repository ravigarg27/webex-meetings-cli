from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import random
from typing import Any, Callable
from urllib.parse import quote, urljoin, urlparse

import httpx

from webex_cli.errors import CliError, DomainCode
from webex_cli.utils.logging import get_logger

logger = get_logger(__name__)


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
    refresh_token_callback: Callable[[], str] | None = None
    _client: httpx.Client | None = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _build_url(self, path: str) -> str:
        return urljoin(f"{self.base_url.rstrip('/')}/", path.lstrip("/"))

    def _base_hostname(self) -> str | None:
        return urlparse(self.base_url).hostname

    @staticmethod
    def _encoded(value: str) -> str:
        return quote(value, safe="")

    @staticmethod
    def _safe_url_for_log(url: str) -> str:
        parsed = urlparse(url)
        host = parsed.hostname or "unknown"
        return f"{parsed.scheme}://{host}{parsed.path or ''}"

    def _map_response_error(self, response: httpx.Response, path: str | None = None) -> CliError:
        status = response.status_code
        details: dict[str, Any] = {"status_code": status}
        code = _normalize_error_code(response)
        if code:
            details["upstream_code"] = code

        if status == 401:
            return CliError(DomainCode.AUTH_INVALID, "Authentication failed or token expired.", details=details)
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

    def _get_client(self) -> httpx.Client:
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

    def _retry_request(
        self,
        *,
        method: str,
        target_for_log: str,
        path_for_error: str | None,
        request_call: Callable[[], httpx.Response],
    ) -> httpx.Response:
        delay = 0.5
        last_error: CliError | None = None
        refreshed_after_401 = False
        for attempt in range(self.retry_attempts):
            try:
                logger.debug("request attempt=%s method=%s target=%s", attempt + 1, method, target_for_log)
                response = request_call()
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.NetworkError) as exc:
                logger.warning("network error method=%s target=%s attempt=%s", method, target_for_log, attempt + 1)
                last_error = CliError(
                    DomainCode.UPSTREAM_UNAVAILABLE,
                    "Network error while calling upstream.",
                    details={"exception": str(exc)},
                )
                if attempt == self.retry_attempts - 1:
                    raise last_error from exc
                wait = random.uniform(0, min(delay, self.max_delay_seconds))
                time.sleep(wait)
                delay *= 2
                continue

            if response.status_code in {429} or response.status_code >= 500:
                logger.warning(
                    "transient upstream response method=%s target=%s status=%s attempt=%s",
                    method,
                    target_for_log,
                    response.status_code,
                    attempt + 1,
                )
                last_error = self._map_response_error(response, path=path_for_error)
                if attempt == self.retry_attempts - 1:
                    raise last_error
                retry_after_delay = self._retry_after_delay(response)
                if retry_after_delay is not None:
                    time.sleep(max(0.0, retry_after_delay))
                else:
                    wait = random.uniform(0, min(delay, self.max_delay_seconds))
                    time.sleep(wait)
                delay *= 2
                continue

            if response.status_code == 401 and self.refresh_token_callback and not refreshed_after_401:
                logger.info("attempting oauth refresh after 401 method=%s target=%s", method, target_for_log)
                new_token = self.refresh_token_callback()
                if not new_token:
                    raise self._map_response_error(response, path=path_for_error)
                self.token = new_token
                refreshed_after_401 = True
                try:
                    response = request_call()
                except (httpx.ConnectError, httpx.ReadTimeout, httpx.NetworkError) as exc:
                    raise CliError(
                        DomainCode.UPSTREAM_UNAVAILABLE,
                        "Network error while calling upstream.",
                        details={"exception": str(exc)},
                    ) from exc

            if response.is_error:
                logger.info(
                    "non-retryable upstream response method=%s target=%s status=%s",
                    method,
                    target_for_log,
                    response.status_code,
                )
                raise self._map_response_error(response, path=path_for_error)
            return response

        if last_error:
            raise last_error
        raise CliError(DomainCode.INTERNAL_ERROR, "Retry loop ended unexpectedly.")

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
    ) -> httpx.Response:
        timeout = timeout_seconds or self.timeout_seconds
        url = self._build_url(path)
        return self._retry_request(
            method=method,
            target_for_log=path,
            path_for_error=path,
            request_call=lambda: self._get_client().request(
                method=method,
                url=url,
                headers=self._headers(),
                params=params,
                timeout=timeout,
            ),
        )

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

    def _request_absolute(
        self,
        method: str,
        url: str,
        *,
        timeout_seconds: int,
        path_for_error: str,
        include_auth: bool,
    ) -> httpx.Response:
        safe_url = self._safe_url_for_log(url)
        return self._retry_request(
            method=method,
            target_for_log=safe_url,
            path_for_error=path_for_error,
            request_call=lambda: self._get_client().request(
                method=method,
                url=url,
                headers=self._headers() if include_auth else None,
                timeout=timeout_seconds,
            ),
        )

    @staticmethod
    def _address_is_private_or_local(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return bool(
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        )

    @staticmethod
    def _host_is_private_or_local(hostname: str) -> bool:
        normalized = hostname.strip().lower()
        if normalized in {"localhost"} or normalized.endswith(".localhost"):
            return True
        try:
            addr = ipaddress.ip_address(normalized)
        except ValueError:
            addr = None
        if addr is not None:
            return WebexApiClient._address_is_private_or_local(addr)

        try:
            resolved = socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return False
        except OSError:
            return False
        for entry in resolved:
            sockaddr = entry[4]
            if not sockaddr:
                continue
            candidate_ip = sockaddr[0]
            try:
                candidate = ipaddress.ip_address(candidate_ip)
            except ValueError:
                continue
            if WebexApiClient._address_is_private_or_local(candidate):
                return True
        return False

    def _validate_download_url(self, url: str) -> tuple[str, bool]:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if parsed.scheme.lower() != "https":
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Recording download URL must use https.",
                details={"download_url": url},
            )
        if not hostname:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Recording download URL is invalid.",
                details={"download_url": url},
            )
        if self._host_is_private_or_local(hostname):
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Recording download URL points to a blocked local/private host.",
                details={"download_host": hostname},
            )

        normalized_host = hostname.lower()
        base_host = (self._base_hostname() or "").lower()
        trusted_suffixes = (
            ".webexapis.com",
            ".webex.com",
            ".cisco.com",
            ".wbx2.com",
        )
        trusted_host = (
            normalized_host == base_host
            or normalized_host in {"webexapis.com", "webex.com"}
            or normalized_host.endswith(trusted_suffixes)
        )
        return url, trusted_host

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
        start = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        self._request_json(
            "GET",
            "/v1/meetings",
            params={"from": start, "to": end, "meetingType": "meeting", "max": 1},
        )

    @staticmethod
    def _normalize_page(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        if not isinstance(payload, dict):
            raise CliError(DomainCode.UPSTREAM_UNAVAILABLE, "Upstream returned invalid pagination payload type.")
        found_items_key = any(key in payload for key in ("items", "meetings", "recordings"))
        items = payload.get("items") or payload.get("meetings") or payload.get("recordings") or []
        if not isinstance(items, list):
            raise CliError(DomainCode.UPSTREAM_UNAVAILABLE, "Upstream returned non-list items payload.")
        if not found_items_key and payload:
            raise CliError(
                DomainCode.UPSTREAM_UNAVAILABLE,
                "Upstream pagination payload missing items key.",
                details={"payload_keys": sorted(payload.keys())[:20]},
            )
        next_token = payload.get("next_page_token") or payload.get("nextPageToken") or payload.get("next")
        return items, next_token

    def list_meetings(
        self,
        *,
        from_utc: str,
        to_utc: str,
        meeting_type: str = "meeting",
        page_size: int,
        page_token: str | None,
        host_email: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        params: dict[str, Any] = {
            "from": from_utc,
            "to": to_utc,
            "meetingType": meeting_type,
            "max": page_size,
        }
        if host_email:
            params["hostEmail"] = host_email
        if page_token:
            params["pageToken"] = page_token
        payload = self._request_json("GET", "/v1/meetings", params=params)
        return self._normalize_page(payload)

    def get_meeting(self, meeting_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/v1/meetings/{self._encoded(meeting_id)}")

    def get_meeting_join_url(self, meeting_id: str) -> dict[str, Any]:
        return self.get_meeting(meeting_id)

    def list_transcripts(self, meeting_id: str) -> list[dict[str, Any]]:
        payload = self._request_json(
            "GET",
            "/v1/meetingTranscripts",
            params={"meetingId": meeting_id},
        )
        items = payload.get("items") or []
        return items if isinstance(items, list) else []

    def download_transcript(self, transcript_id: str, format_value: str) -> bytes:
        response = self._request(
            "GET",
            f"/v1/meetingTranscripts/{self._encoded(transcript_id)}/download",
            params={"format": format_value},
            timeout_seconds=self.download_timeout_seconds,
        )
        return response.content

    def list_recordings(
        self,
        *,
        from_utc: str,
        to_utc: str,
        page_size: int,
        page_token: str | None,
        host_email: str | None = None,
        meeting_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        params: dict[str, Any] = {"from": from_utc, "to": to_utc, "max": page_size}
        if host_email:
            params["hostEmail"] = host_email
        if page_token:
            params["pageToken"] = page_token
        if meeting_id:
            params["meetingId"] = meeting_id
        payload = self._request_json("GET", "/v1/recordings", params=params)
        return self._normalize_page(payload)

    def get_recording(self, recording_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/v1/recordings/{self._encoded(recording_id)}")

    def list_recordings_for_meeting(self, meeting_id: str) -> list[dict[str, Any]]:
        all_items: list[dict[str, Any]] = []
        token: str | None = None
        while True:
            params: dict[str, Any] = {"meetingId": meeting_id, "max": 200}
            if token:
                params["pageToken"] = token
            payload = self._request_json("GET", "/v1/recordings", params=params)
            items, token = self._normalize_page(payload)
            all_items.extend(items)
            if not token:
                break
        return all_items

    @staticmethod
    def _select_download_link(metadata: dict[str, Any], quality: str) -> tuple[str | None, str]:
        direct = metadata.get("downloadUrl") or metadata.get("download_url")
        if direct:
            actual_quality = str(metadata.get("quality") or quality)
            return str(direct), actual_quality

        links = metadata.get("temporaryDirectDownloadLinks") or {}
        if not isinstance(links, dict):
            return None, quality

        normalized_links = {str(k).lower(): str(v) for k, v in links.items() if v}
        canonical_order = ["best", "high", "medium"]
        fallback_order = [quality] + [q for q in canonical_order if q != quality]
        for candidate_quality in fallback_order:
            url = normalized_links.get(candidate_quality)
            if url:
                return url, candidate_quality
        # Fallback to any other upstream quality key when present.
        for candidate_quality in sorted(normalized_links):
            return normalized_links[candidate_quality], candidate_quality
        return None, quality

    def download_recording(self, recording_id: str, quality: str) -> tuple[bytes, str]:
        metadata = self.get_recording(recording_id)
        download_url, actual_quality = self._select_download_link(metadata, quality)
        if not download_url:
            raise CliError(
                DomainCode.NOT_FOUND,
                "Recording download URL not available.",
                details={"recording_id": recording_id},
            )
        safe_url, trusted_host = self._validate_download_url(download_url)
        response = self._request_absolute(
            "GET",
            safe_url,
            timeout_seconds=self.download_timeout_seconds,
            path_for_error="/v1/recordings/download",
            include_auth=trusted_host,
        )
        return response.content, str(actual_quality)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
