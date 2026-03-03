from __future__ import annotations

import typer

from webex_cli.errors import CliError, DomainCode
from webex_cli.output.human import emit_error_human, emit_success_human
from webex_cli.output.json_renderer import emit_error_json, emit_success_json


def emit_success(command: str, data: object, as_json: bool, warnings: list[str] | None = None) -> None:
    if as_json:
        emit_success_json(command=command, data=data, warnings=warnings or [])
    else:
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
            details={"exception": str(exc)},
        ),
        as_json,
    )

