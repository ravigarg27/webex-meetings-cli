from __future__ import annotations

from contextlib import contextmanager
import os
import re
import threading
from typing import Any, Callable, Iterator
from urllib.parse import urlparse

import typer

from webex_cli.client import WebexApiClient
from webex_cli.config import CredentialStore, ProfileStore, load_settings
from webex_cli.config.credentials import CredentialRecord
from webex_cli.errors import CliError, DomainCode
from webex_cli.oauth import is_expiring_soon, refresh_access_token, resolve_oauth_device_config
from webex_cli.output.human import emit_error_human, emit_success_human, emit_warnings_human
from webex_cli.output.json_renderer import emit_error_json, emit_success_json
from webex_cli.runtime import get_current_profile, get_duration_ms, get_request_id, use_profile

_REFRESH_LOCKS: dict[str, threading.Lock] = {}
_REFRESH_LOCKS_GUARD = threading.Lock()


def emit_success(command: str, data: object, as_json: bool, warnings: list[str] | None = None) -> None:
    request_id = get_request_id()
    duration_ms = get_duration_ms()
    if as_json:
        emit_success_json(
            command=command,
            data=data,
            warnings=warnings or [],
            request_id=request_id,
            duration_ms=duration_ms,
        )
    else:
        if warnings:
            emit_warnings_human(warnings)
        emit_success_human(data)


def fail(command: str, error: CliError, as_json: bool) -> None:
    request_id = get_request_id()
    duration_ms = get_duration_ms()
    if as_json:
        emit_error_json(command=command, error=error, request_id=request_id, duration_ms=duration_ms)
    else:
        emit_error_human(error)
    raise typer.Exit(code=error.exit_code)


def handle_unexpected(command: str, as_json: bool, exc: Exception) -> None:
    fail(
        command,
        CliError(
            DomainCode.INTERNAL_ERROR,
            "Unexpected internal error.",
            details={"error_type": type(exc).__name__},
        ),
        as_json,
    )


def resolve_base_url() -> str:
    settings = load_settings()
    env_base_url = os.environ.get("WEBEX_API_BASE_URL")
    base_url = env_base_url or settings.api_base_url
    from_env = env_base_url is not None
    parsed = urlparse(base_url)
    if parsed.scheme.lower() != "https":
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "API base URL must use https.",
            details={"api_base_url": base_url},
        )
    if not parsed.netloc:
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "API base URL is invalid.",
            details={"api_base_url": base_url},
        )
    hostname = (parsed.hostname or "").lower()
    trusted = hostname == "webexapis.com" or hostname.endswith(".webexapis.com")
    if not trusted and not from_env and os.environ.get("WEBEX_ALLOW_CUSTOM_API_BASE_URL") != "1":
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "Untrusted API base URL from config is blocked. Use WEBEX_API_BASE_URL or set WEBEX_ALLOW_CUSTOM_API_BASE_URL=1.",
            details={"api_base_url": base_url},
        )
    return base_url.rstrip("/")


def resolve_effective_timezone(cli_tz: str | None) -> str | None:
    if cli_tz:
        return cli_tz
    profile_key = resolve_profile()
    profile_tz = ProfileStore().profile_default_tz(profile_key)
    if profile_tz:
        return profile_tz
    settings = load_settings()
    return settings.default_tz


def resolve_profile() -> str:
    explicit = get_current_profile()
    env_profile = os.environ.get("WEBEX_PROFILE")
    preferred = explicit if explicit else env_profile
    return ProfileStore().resolve(preferred=preferred)


def load_token() -> str:
    return load_credential_record().token


def _profile_refresh_lock(profile_key: str) -> threading.Lock:
    with _REFRESH_LOCKS_GUARD:
        lock = _REFRESH_LOCKS.get(profile_key)
        if lock is None:
            lock = threading.Lock()
            _REFRESH_LOCKS[profile_key] = lock
        return lock


def _refresh_oauth_record(profile_key: str, *, force: bool) -> CredentialRecord:
    lock = _profile_refresh_lock(profile_key)
    with lock:
        store = CredentialStore(profile=profile_key)
        current = store.load()
        if current.auth_type != "oauth":
            return current
        if not force and not is_expiring_soon(current.expires_at):
            return current
        if not current.refresh_token:
            store.mark_invalid("invalid")
            raise CliError(
                DomainCode.AUTH_INVALID,
                "OAuth session is missing a refresh token. Re-authenticate.",
                details={"auth_cause": "invalid"},
            )

        try:
            config = resolve_oauth_device_config()
            refreshed = refresh_access_token(config, current.refresh_token)
        except CliError as exc:
            if exc.code == DomainCode.AUTH_INVALID:
                cause = str((exc.details or {}).get("auth_cause") or "invalid")
                store.mark_invalid(cause)
            raise

        store.save(
            CredentialRecord(
                token=refreshed.access_token,
                auth_type="oauth",
                refresh_token=refreshed.refresh_token or current.refresh_token,
                expires_at=refreshed.expires_at,
                scopes=refreshed.scopes,
                invalid_reason=None,
            )
        )
        store.clear_invalid()
        return store.load()


def _refresh_oauth_token(profile_key: str) -> str:
    record = _refresh_oauth_record(profile_key, force=True)
    return record.token


def load_credential_record() -> CredentialRecord:
    profile_key = resolve_profile()
    store = CredentialStore(profile=profile_key)
    record = store.load()
    if record.invalid_reason:
        raise CliError(
            DomainCode.AUTH_INVALID,
            "Stored OAuth session is invalid. Run `webex auth login` again.",
            details={"auth_cause": record.invalid_reason},
        )
    if record.auth_type == "oauth":
        record = _refresh_oauth_record(profile_key, force=False)
    return record


def build_client(token: str | None = None) -> WebexApiClient:
    if token is not None:
        return WebexApiClient(base_url=resolve_base_url(), token=token)

    profile_key = resolve_profile()
    record = load_credential_record()
    refresh_callback: Callable[[], str] | None = None
    if record.auth_type == "oauth":
        refresh_callback = lambda: _refresh_oauth_token(profile_key)
    return WebexApiClient(
        base_url=resolve_base_url(),
        token=record.token,
        refresh_token_callback=refresh_callback,
    )


@contextmanager
def managed_client(
    token: str | None = None,
    *,
    client_factory: Callable[[str | None], WebexApiClient] | None = None,
) -> Iterator[WebexApiClient]:
    factory = client_factory or build_client
    client = factory(token)
    try:
        yield client
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def fetch_all_pages(
    fetch_page: Callable[[str | None], tuple[list[dict[str, Any]], str | None]],
    *,
    start_token: str | None = None,
    max_items: int = 10000,
) -> tuple[list[dict[str, Any]], list[str]]:
    token = start_token
    items: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_tokens: set[str] = set()
    if token:
        seen_tokens.add(token)
    while True:
        previous_count = len(items)
        page_items, next_token = fetch_page(token)
        items.extend(page_items)
        if len(items) > max_items or (len(items) >= max_items and bool(next_token)):
            warnings.append("MAX_ITEMS_GUARD_HIT")
            raise CliError(
                DomainCode.RESULT_SET_TOO_LARGE,
                "Result set exceeded max item guard.",
                details={
                    "max_items": max_items,
                    "warnings": warnings,
                    "resume_page_token": next_token,
                },
            )
        if len(items) == max_items and not next_token:
            warnings.append("MAX_ITEMS_GUARD_HIT")
        if not next_token:
            break
        if token is not None and next_token == token:
            raise CliError(
                DomainCode.UPSTREAM_UNAVAILABLE,
                "Pagination token repeated with no progress.",
                details={"reason": "PAGINATION_CYCLE", "page_token": next_token},
            )
        if next_token in seen_tokens:
            raise CliError(
                DomainCode.UPSTREAM_UNAVAILABLE,
                "Pagination loop detected.",
                details={"reason": "PAGINATION_CYCLE", "page_token": next_token},
            )
        if len(items) == previous_count and not page_items:
            raise CliError(
                DomainCode.UPSTREAM_UNAVAILABLE,
                "Pagination made no progress.",
                details={"reason": "PAGINATION_NO_PROGRESS", "page_token": next_token},
            )
        seen_tokens.add(next_token)
        token = next_token
    return items, warnings


_ID_PATTERN = re.compile(r"^\S+$")


def validate_id(value: str, name: str = "id") -> str:
    candidate = value.strip()
    if not candidate or not _ID_PATTERN.match(candidate):
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            f"Invalid {name} format.",
            details={name: value},
        )
    return candidate


@contextmanager
def profile_scope(profile: str | None) -> Iterator[None]:
    if profile is None:
        yield
        return
    with use_profile(profile):
        yield
