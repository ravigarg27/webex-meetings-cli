from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from webex_cli.config.settings import load_settings
from webex_cli.errors import CliError, DomainCode

DEFAULT_DEVICE_AUTHORIZE_URL = "https://webexapis.com/v1/device/authorize"
DEFAULT_TOKEN_URL = "https://webexapis.com/v1/device/token"
DEFAULT_SCOPES = "spark:all"
DEFAULT_POLL_INTERVAL_SECONDS = 5
MIN_POLL_INTERVAL_SECONDS = 2
MAX_POLL_INTERVAL_SECONDS = 30
DEFAULT_TIMEOUT_SECONDS = 600


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


@dataclass(frozen=True)
class OAuthDeviceConfig:
    client_id: str
    device_authorize_url: str
    token_url: str
    scope: str
    poll_interval_seconds: int
    timeout_seconds: int


@dataclass(frozen=True)
class OAuthTokenBundle:
    access_token: str
    refresh_token: str | None
    expires_at: str | None
    scopes: list[str]


def _validated_https_url(raw_value: str, field_name: str) -> str:
    value = raw_value.strip()
    parsed = urlparse(value)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            f"Invalid OAuth URL for {field_name}.",
            details={field_name: raw_value},
        )
    return value


def _parse_scopes(raw_scope: str) -> list[str]:
    return [item for item in (part.strip() for part in raw_scope.split()) if item]


def _expires_at(expires_in_seconds: int | None) -> str | None:
    if not expires_in_seconds or expires_in_seconds <= 0:
        return None
    expires = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
    return expires.isoformat()


def resolve_oauth_device_config(
    *,
    client_id: str | None = None,
    device_authorize_url: str | None = None,
    token_url: str | None = None,
    scope: str | None = None,
    poll_interval_seconds: int | None = None,
    timeout_seconds: int | None = None,
) -> OAuthDeviceConfig:
    settings = load_settings()

    resolved_client_id = client_id or os.environ.get("WEBEX_OAUTH_CLIENT_ID") or settings.oauth_client_id
    normalized_client_id = str(resolved_client_id).strip() if resolved_client_id is not None else ""
    if not normalized_client_id:
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "OAuth device flow requires a client ID. Set --oauth-client-id, WEBEX_OAUTH_CLIENT_ID, or config.oauth_client_id.",
        )

    resolved_authorize_url = (
        device_authorize_url
        or os.environ.get("WEBEX_OAUTH_DEVICE_AUTHORIZE_URL")
        or settings.oauth_device_authorize_url
        or DEFAULT_DEVICE_AUTHORIZE_URL
    )
    resolved_token_url = token_url or os.environ.get("WEBEX_OAUTH_TOKEN_URL") or settings.oauth_token_url or DEFAULT_TOKEN_URL
    resolved_scope = scope or os.environ.get("WEBEX_OAUTH_SCOPE") or settings.oauth_scope or DEFAULT_SCOPES
    resolved_poll = _coalesce(
        poll_interval_seconds,
        _parse_int_env("WEBEX_OAUTH_POLL_INTERVAL"),
        settings.oauth_poll_interval_seconds,
        DEFAULT_POLL_INTERVAL_SECONDS,
    )
    resolved_timeout = _coalesce(
        timeout_seconds,
        _parse_int_env("WEBEX_OAUTH_TIMEOUT"),
        settings.oauth_timeout_seconds,
        DEFAULT_TIMEOUT_SECONDS,
    )

    if resolved_poll < MIN_POLL_INTERVAL_SECONDS or resolved_poll > MAX_POLL_INTERVAL_SECONDS:
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            f"OAuth poll interval must be between {MIN_POLL_INTERVAL_SECONDS} and {MAX_POLL_INTERVAL_SECONDS} seconds.",
            details={"poll_interval_seconds": resolved_poll},
        )
    if resolved_timeout <= 0:
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "OAuth timeout must be a positive integer.",
            details={"timeout_seconds": resolved_timeout},
        )

    return OAuthDeviceConfig(
        client_id=normalized_client_id,
        device_authorize_url=_validated_https_url(resolved_authorize_url, "oauth_device_authorize_url"),
        token_url=_validated_https_url(resolved_token_url, "oauth_token_url"),
        scope=resolved_scope.strip(),
        poll_interval_seconds=resolved_poll,
        timeout_seconds=resolved_timeout,
    )


def _parse_int_env(name: str) -> int | None:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return None
    try:
        return int(raw_value)
    except ValueError as exc:
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            f"Environment variable {name} must be an integer.",
            details={name: raw_value},
        ) from exc


def start_device_authorization(config: OAuthDeviceConfig) -> dict[str, Any]:
    data = {
        "client_id": config.client_id,
        "scope": config.scope,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(config.device_authorize_url, data=data)
    except httpx.HTTPError as exc:
        raise CliError(
            DomainCode.UPSTREAM_UNAVAILABLE,
            "Unable to start OAuth device authorization.",
            details={"exception": str(exc)},
        ) from exc

    payload = _parse_oauth_json(response, operation="device_authorization")
    oauth_error = str(payload.get("error") or "").strip().lower()
    if oauth_error:
        details: dict[str, Any] = {"oauth_error": oauth_error}
        error_description = payload.get("error_description")
        if isinstance(error_description, str) and error_description.strip():
            details["oauth_error_description"] = error_description.strip()
        if oauth_error in {"invalid_client", "unauthorized_client", "invalid_scope"}:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "OAuth device authorization rejected due to invalid OAuth configuration.",
                details=details,
            )
        raise CliError(
            DomainCode.AUTH_INVALID,
            "OAuth device authorization failed.",
            details={"auth_cause": "invalid", **details},
        )
    device_code = str(payload.get("device_code") or "")
    user_code = str(payload.get("user_code") or "")
    verify_uri = str(payload.get("verification_uri") or payload.get("verificationUri") or "")
    verify_uri_complete = str(
        payload.get("verification_uri_complete")
        or payload.get("verificationUriComplete")
        or ""
    )
    if not device_code or not user_code or not (verify_uri or verify_uri_complete):
        raise CliError(
            DomainCode.UPSTREAM_UNAVAILABLE,
            "OAuth device authorization payload is missing required fields.",
            details={"payload_keys": sorted(payload.keys())[:20]},
        )
    interval = payload.get("interval")
    interval_seconds = config.poll_interval_seconds
    if isinstance(interval, int):
        interval_seconds = max(MIN_POLL_INTERVAL_SECONDS, min(MAX_POLL_INTERVAL_SECONDS, interval))

    return {
        "device_code": device_code,
        "user_code": user_code,
        "verification_uri": verify_uri,
        "verification_uri_complete": verify_uri_complete,
        "expires_in": int(payload.get("expires_in") or payload.get("expiresIn") or config.timeout_seconds),
        "interval_seconds": interval_seconds,
    }


def poll_for_device_token(
    config: OAuthDeviceConfig,
    *,
    device_code: str,
    interval_seconds: int,
) -> OAuthTokenBundle:
    started = time.monotonic()
    poll_interval = interval_seconds
    with httpx.Client(timeout=30.0) as client:
        while True:
            if (time.monotonic() - started) >= config.timeout_seconds:
                raise CliError(
                    DomainCode.AUTH_INVALID,
                    "OAuth device flow timed out before authorization completed.",
                    details={"auth_cause": "expired_token"},
                )

            time.sleep(poll_interval)
            payload = _token_exchange(
                config,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                    "client_id": config.client_id,
                },
                client=client,
            )
            oauth_error = payload.get("error")
            if not oauth_error:
                return _bundle_from_payload(payload, fallback_scope=config.scope)
            normalized = str(oauth_error).strip()
            if normalized == "authorization_pending":
                continue
            if normalized == "slow_down":
                poll_interval = min(MAX_POLL_INTERVAL_SECONDS, poll_interval + 5)
                continue
            if normalized == "access_denied":
                raise CliError(
                    DomainCode.AUTH_INVALID,
                    "OAuth authorization was denied by the user.",
                    details={"auth_cause": "access_denied"},
                )
            if normalized == "expired_token":
                raise CliError(
                    DomainCode.AUTH_INVALID,
                    "OAuth device code expired. Run `webex auth login --oauth-device-flow` again.",
                    details={"auth_cause": "expired_token"},
                )
            raise CliError(
                DomainCode.AUTH_INVALID,
                "OAuth device flow failed.",
                details={"auth_cause": "invalid", "oauth_error": normalized},
            )


def refresh_access_token(config: OAuthDeviceConfig, refresh_token: str) -> OAuthTokenBundle:
    payload = _token_exchange(
        config,
        data={
            "grant_type": "refresh_token",
            "client_id": config.client_id,
            "refresh_token": refresh_token,
        },
    )
    oauth_error = payload.get("error")
    if oauth_error:
        normalized = str(oauth_error).strip()
        auth_cause = "invalid"
        if normalized in {"invalid_grant", "invalid_token"}:
            auth_cause = "revoked"
        raise CliError(
            DomainCode.AUTH_INVALID,
            "OAuth refresh token is no longer valid. Re-authenticate.",
            details={"auth_cause": auth_cause, "oauth_error": normalized},
        )
    return _bundle_from_payload(payload, fallback_scope=config.scope)


def _token_exchange(
    config: OAuthDeviceConfig,
    data: dict[str, str],
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    try:
        if client is not None:
            response = client.post(config.token_url, data=data)
        else:
            with httpx.Client(timeout=30.0) as local_client:
                response = local_client.post(config.token_url, data=data)
    except httpx.HTTPError as exc:
        raise CliError(
            DomainCode.UPSTREAM_UNAVAILABLE,
            "OAuth token endpoint is unavailable.",
            details={"exception": str(exc)},
        ) from exc
    return _parse_oauth_json(response, operation="token_exchange")


def _parse_oauth_json(response: httpx.Response, *, operation: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        raise CliError(
            DomainCode.UPSTREAM_UNAVAILABLE,
            "OAuth endpoint returned invalid JSON.",
            details={"operation": operation, "status_code": response.status_code},
        ) from exc
    if not isinstance(payload, dict):
        raise CliError(
            DomainCode.UPSTREAM_UNAVAILABLE,
            "OAuth endpoint returned a non-object JSON payload.",
            details={"operation": operation, "status_code": response.status_code},
        )
    if response.status_code >= 500:
        raise CliError(
            DomainCode.UPSTREAM_UNAVAILABLE,
            "OAuth endpoint is unavailable.",
            details={"operation": operation, "status_code": response.status_code},
        )
    if response.status_code not in {200, 400}:
        raise CliError(
            DomainCode.AUTH_INVALID,
            "OAuth request failed.",
            details={"operation": operation, "status_code": response.status_code},
        )
    return payload


def _bundle_from_payload(payload: dict[str, Any], *, fallback_scope: str) -> OAuthTokenBundle:
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        raise CliError(
            DomainCode.AUTH_INVALID,
            "OAuth token response did not include an access token.",
            details={"auth_cause": "invalid"},
        )
    refresh_token = payload.get("refresh_token")
    expires_in_raw = payload.get("expires_in")
    expires_in = int(expires_in_raw) if isinstance(expires_in_raw, int) or str(expires_in_raw).isdigit() else None
    scope_raw = str(payload.get("scope") or fallback_scope)
    return OAuthTokenBundle(
        access_token=access_token,
        refresh_token=str(refresh_token) if refresh_token else None,
        expires_at=_expires_at(expires_in),
        scopes=_parse_scopes(scope_raw),
    )


def is_expiring_soon(expires_at: str | None, *, threshold_seconds: int = 120) -> bool:
    if not expires_at:
        return False
    try:
        dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    remaining = (dt.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()
    return remaining <= threshold_seconds
