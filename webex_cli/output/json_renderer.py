from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import typer

from webex_cli.errors import CliError
from webex_cli.version import SCHEMA_VERSION, __version__
from webex_cli.utils.redaction import redact_value


def _meta(
    request_id: str | None = None,
    duration_ms: int | None = None,
    *,
    profile: str | None = None,
    command_mode: str = "read",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "request_id": request_id or str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cli_version": __version__,
        "schema_version": SCHEMA_VERSION,
        "duration_ms": 0 if duration_ms is None else duration_ms,
        "profile": profile,
        "command_mode": command_mode,
    }
    return payload


def emit_success_json(
    command: str,
    data: Any,
    warnings: list[str] | None = None,
    request_id: str | None = None,
    duration_ms: int | None = None,
    *,
    profile: str | None = None,
    command_mode: str = "read",
) -> None:
    payload = {
        "ok": True,
        "command": command,
        "data": data,
        "warnings": warnings or [],
        "error": None,
        "meta": _meta(
            request_id=request_id,
            duration_ms=duration_ms,
            profile=profile,
            command_mode=command_mode,
        ),
    }
    typer.echo(json.dumps(payload, indent=2, default=str))


def emit_error_json(
    command: str,
    error: CliError,
    request_id: str | None = None,
    duration_ms: int | None = None,
    *,
    profile: str | None = None,
    command_mode: str = "read",
) -> None:
    payload = {
        "ok": False,
        "command": command,
        "data": None,
        "warnings": [],
        "error": {
            "code": error.error_code or error.code.value,
            "message": error.message,
            "retryable": error.retryable,
            "details": redact_value(error.details),
        },
        "meta": _meta(
            request_id=request_id,
            duration_ms=duration_ms,
            profile=profile,
            command_mode=command_mode,
        ),
    }
    typer.echo(json.dumps(payload, indent=2, default=str))
