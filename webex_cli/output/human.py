from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import typer

from webex_cli.errors import CliError

_WARNING_MESSAGES: dict[str, str] = {
    "INSECURE_CREDENTIAL_STORE": (
        "Credentials are stored in a plain-text file because the system keyring is unavailable. "
        "Keep this file secure."
    ),
    "TOKEN_CLI_ARGUMENT_INSECURE": (
        "Token was passed via --token and may appear in shell history. "
        "Prefer the WEBEX_TOKEN environment variable or --token-stdin."
    ),
    "UNMAPPED_TRANSCRIPT_STATUS": "Unrecognised transcript status received from Webex.",
    "UNMAPPED_RECORDING_STATUS": "Unrecognised recording status received from Webex.",
    "QUALITY_FALLBACK": "Requested recording quality was unavailable; a lower quality was downloaded instead.",
    "MAX_ITEMS_GUARD_HIT": "Result set reached the item limit and may be incomplete.",
}

# Fields that are internal / noisy and not shown in plain human output.
_HUMAN_SKIP_FIELDS: frozenset[str] = frozenset({"user_id", "org_id", "token_state", "credential_backend"})

_ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _format_timestamp(value: str) -> str:
    """Render an ISO 8601 timestamp as a short, readable UTC string."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return value


def _to_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _format_timestamp(value) if _ISO_TIMESTAMP_RE.match(value) else value
    return json.dumps(value, ensure_ascii=False, default=str)


def _emit_table(items: list[dict[str, Any]]) -> bool:
    if not items:
        typer.echo("(no items)")
        return True
    if not all(isinstance(item, dict) for item in items):
        return False
    headers = list(items[0].keys())
    widths: dict[str, int] = {h: len(h) for h in headers}
    rows: list[dict[str, str]] = []
    for item in items:
        row: dict[str, str] = {}
        for header in headers:
            cell = _to_cell(item.get(header))
            row[header] = cell
            widths[header] = max(widths[header], len(cell))
        rows.append(row)
    header_line = "  ".join(header.ljust(widths[header]) for header in headers)
    sep_line = "  ".join("-" * widths[header] for header in headers)
    typer.echo(header_line)
    typer.echo(sep_line)
    for row in rows:
        typer.echo("  ".join(row[header].ljust(widths[header]) for header in headers))
    return True


def emit_success_human(data: Any) -> None:
    if isinstance(data, str):
        typer.echo(data)
        return
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list) and _emit_table(items):
            extra = {k: v for k, v in data.items() if k != "items" and v is not None and v != ""}
            for key, value in extra.items():
                typer.echo(f"{key}: {_to_cell(value)}")
            return
        if {"total_meetings", "success", "skipped", "failed"}.issubset(data.keys()):
            total = _to_cell(data.get("total_meetings"))
            success = _to_cell(data.get("success"))
            skipped = _to_cell(data.get("skipped"))
            failed = _to_cell(data.get("failed"))
            typer.echo(f"Downloaded:  {success}")
            typer.echo(f"Skipped:     {skipped}")
            typer.echo(f"Failed:      {failed}")
            typer.echo(f"Total:       {total}")
            results = data.get("results")
            if isinstance(results, list):
                display = []
                for r in results:
                    if not isinstance(r, dict):
                        continue
                    row = {k: v for k, v in r.items() if k != "error_code"}
                    if "error_message" in row:
                        row["note"] = row.pop("error_message")
                    display.append(row)
                _emit_table(display)
            return
        simple = all(isinstance(v, (str, int, float, bool, type(None))) for v in data.values())
        if simple:
            for key, value in data.items():
                if key in _HUMAN_SKIP_FIELDS:
                    continue
                cell = _to_cell(value)
                if cell == "":
                    continue
                typer.echo(f"{key}: {cell}")
            return
    typer.echo(json.dumps(data, indent=2, default=str))


def emit_warnings_human(warnings: list[str]) -> None:
    for warning in warnings:
        msg = _WARNING_MESSAGES.get(warning, warning)
        typer.echo(f"Warning: {msg}", err=True)


def emit_error_human(error: CliError) -> None:
    typer.echo(f"Error: {error.message}", err=True)
    if error.details:
        details_str = "  ".join(f"{k}={v}" for k, v in error.details.items())
        typer.echo(f"  {details_str}", err=True)
