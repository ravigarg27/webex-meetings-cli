from __future__ import annotations

import typer

from webex_cli.commands.common import emit_success

meeting_app = typer.Typer(help="Meeting commands")


@meeting_app.command("list")
def list_meetings(
    from_value: str = typer.Option(..., "--from"),
    to_value: str = typer.Option(..., "--to"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    emit_success(
        "meeting list",
        {"status": "not_implemented", "from": from_value, "to": to_value},
        as_json=json_output,
    )


@meeting_app.command("get")
def get_meeting(meeting_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    emit_success("meeting get", {"status": "not_implemented", "meeting_id": meeting_id}, as_json=json_output)


@meeting_app.command("join-url")
def join_url(meeting_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    emit_success(
        "meeting join-url",
        {"status": "not_implemented", "meeting_id": meeting_id},
        as_json=json_output,
    )

