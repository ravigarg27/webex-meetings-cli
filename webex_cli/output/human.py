from __future__ import annotations

import json
from typing import Any

import typer

from webex_cli.errors import CliError


def emit_success_human(data: Any) -> None:
    if isinstance(data, str):
        typer.echo(data)
        return
    typer.echo(json.dumps(data, indent=2, default=str))


def emit_warnings_human(warnings: list[str]) -> None:
    for warning in warnings:
        typer.echo(f"warning: {warning}", err=True)


def emit_error_human(error: CliError) -> None:
    typer.echo(f"error[{error.code.value}]: {error.message}", err=True)
    if error.details:
        typer.echo(json.dumps(error.details, indent=2, default=str), err=True)
