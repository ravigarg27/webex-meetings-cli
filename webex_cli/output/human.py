from __future__ import annotations

import json
from typing import Any

import typer

from webex_cli.errors import CliError


def _to_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
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
            extra = {k: v for k, v in data.items() if k != "items"}
            for key, value in extra.items():
                typer.echo(f"{key}: {_to_cell(value)}")
            return
        if {"total_meetings", "success", "skipped", "failed"}.issubset(data.keys()):
            typer.echo(
                "summary: "
                f"total={_to_cell(data.get('total_meetings'))} "
                f"success={_to_cell(data.get('success'))} "
                f"skipped={_to_cell(data.get('skipped'))} "
                f"failed={_to_cell(data.get('failed'))}"
            )
            results = data.get("results")
            if isinstance(results, list):
                _emit_table([r for r in results if isinstance(r, dict)])
            return
        simple = all(isinstance(v, (str, int, float, bool, type(None))) for v in data.values())
        if simple:
            for key, value in data.items():
                typer.echo(f"{key}: {_to_cell(value)}")
            return
    typer.echo(json.dumps(data, indent=2, default=str))


def emit_warnings_human(warnings: list[str]) -> None:
    for warning in warnings:
        typer.echo(f"warning: {warning}", err=True)


def emit_error_human(error: CliError) -> None:
    typer.echo(f"error[{error.code.value}]: {error.message}", err=True)
    if error.details:
        typer.echo(json.dumps(error.details, indent=2, default=str), err=True)
