from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import typer

from webex_cli.errors import CliError
from webex_cli.version import SCHEMA_VERSION, __version__
from webex_cli.utils.redaction import redact_value


def _meta(request_id: str | None = None, duration_ms: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "request_id": request_id or str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cli_version": __version__,
        "schema_version": SCHEMA_VERSION,
    }
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    return payload


def emit_success_json(
    command: str,
    data: Any,
    warnings: list[str] | None = None,
    request_id: str | None = None,
    duration_ms: int | None = None,
) -> None:
    payload = {
        "ok": True,
        "command": command,
        "data": data,
        "warnings": warnings or [],
        "error": None,
        "meta": _meta(request_id=request_id, duration_ms=duration_ms),
    }
    typer.echo(json.dumps(payload, indent=2, default=str))


def emit_error_json(
    command: str,
    error: CliError,
    request_id: str | None = None,
    duration_ms: int | None = None,
) -> None:
    payload = {
        "ok": False,
        "command": command,
        "data": None,
        "warnings": [],
        "error": {
            "code": error.code.value,
            "message": error.message,
            "retryable": error.retryable,
            "details": redact_value(error.details),
        },
        "meta": _meta(request_id=request_id, duration_ms=duration_ms),
    }
    typer.echo(json.dumps(payload, indent=2, default=str))
