from __future__ import annotations

from contextlib import contextmanager
import inspect
import os
import re
from typing import Any, Callable, Iterator
from urllib.parse import urlparse

import typer

from webex_cli.client import WebexApiClient
from webex_cli.config import CredentialStore, load_settings
from webex_cli.errors import CliError, DomainCode
from webex_cli.output.human import emit_error_human, emit_success_human, emit_warnings_human
from webex_cli.output.json_renderer import emit_error_json, emit_success_json


def emit_success(command: str, data: object, as_json: bool, warnings: list[str] | None = None) -> None:
    if as_json:
        emit_success_json(command=command, data=data, warnings=warnings or [])
    else:
        if warnings:
            emit_warnings_human(warnings)
        emit_success_human(data)


def fail(command: str, error: CliError, as_json: bool) -> None:
    if as_json:
        emit_error_json(command=command, error=error)
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
    base_url = os.environ.get("WEBEX_API_BASE_URL") or settings.api_base_url
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
    return base_url.rstrip("/")


def resolve_effective_timezone(cli_tz: str | None) -> str | None:
    if cli_tz:
        return cli_tz
    settings = load_settings()
    return settings.default_tz


def load_token() -> str:
    record = CredentialStore().load()
    return record.token


def build_client(token: str | None = None) -> WebexApiClient:
    return WebexApiClient(base_url=resolve_base_url(), token=token or load_token())


@contextmanager
def managed_client(
    token: str | None = None,
    *,
    client_factory: Callable[[str | None], WebexApiClient] | None = None,
) -> Iterator[WebexApiClient]:
    factory = client_factory or build_client
    if token is None:
        signature: inspect.Signature | None = None
        try:
            signature = inspect.signature(factory)
        except (TypeError, ValueError):
            signature = None
        if signature is not None and len(signature.parameters) == 0:
            # Some tests monkeypatch a zero-arg factory; support both forms.
            client = factory()
        else:
            client = factory(token)
    else:
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
    while True:
        page_items, next_token = fetch_page(token)
        items.extend(page_items)
        if len(items) > max_items or (len(items) >= max_items and bool(next_token)):
            warnings.append("MAX_ITEMS_GUARD_HIT")
            raise CliError(
                DomainCode.UPSTREAM_UNAVAILABLE,
                "Result set exceeded max item guard.",
                details={"max_items": max_items, "warnings": warnings},
            )
        if len(items) == max_items and not next_token:
            warnings.append("MAX_ITEMS_GUARD_HIT")
        if not next_token:
            break
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
