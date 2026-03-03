from __future__ import annotations

import typer

from webex_cli.commands.common import emit_success

recording_app = typer.Typer(help="Recording commands")


@recording_app.command("list")
def list_recordings(
    from_value: str = typer.Option(..., "--from"),
    to_value: str = typer.Option(..., "--to"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    emit_success(
        "recording list",
        {"status": "not_implemented", "from": from_value, "to": to_value},
        as_json=json_output,
    )


@recording_app.command("status")
def status_recording(
    meeting_id: str,
    recording_id: str | None = typer.Option(None, "--recording-id"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    emit_success(
        "recording status",
        {"status": "not_implemented", "meeting_id": meeting_id, "recording_id": recording_id},
        as_json=json_output,
    )


@recording_app.command("download")
def download_recording(
    meeting_id: str,
    out: str = typer.Option(..., "--out"),
    recording_id: str | None = typer.Option(None, "--recording-id"),
    quality: str = typer.Option("best", "--quality"),
    overwrite: bool = typer.Option(False, "--overwrite"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    emit_success(
        "recording download",
        {
            "status": "not_implemented",
            "meeting_id": meeting_id,
            "recording_id": recording_id,
            "out": out,
            "quality": quality,
            "overwrite": overwrite,
        },
        as_json=json_output,
    )

