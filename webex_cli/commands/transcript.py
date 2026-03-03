from __future__ import annotations

import typer

from webex_cli.commands.common import emit_success

transcript_app = typer.Typer(help="Transcript commands")


@transcript_app.command("status")
def status(meeting_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    emit_success(
        "transcript status",
        {"status": "not_implemented", "meeting_id": meeting_id},
        as_json=json_output,
    )


@transcript_app.command("get")
def get_transcript(
    meeting_id: str,
    format_value: str = typer.Option("text", "--format"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    emit_success(
        "transcript get",
        {"status": "not_implemented", "meeting_id": meeting_id, "format": format_value},
        as_json=json_output,
    )


@transcript_app.command("wait")
def wait_transcript(
    meeting_id: str,
    timeout: int = typer.Option(600, "--timeout"),
    interval: int = typer.Option(10, "--interval"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    emit_success(
        "transcript wait",
        {"status": "not_implemented", "meeting_id": meeting_id, "timeout": timeout, "interval": interval},
        as_json=json_output,
    )


@transcript_app.command("download")
def download_transcript(
    meeting_id: str,
    format_value: str = typer.Option(..., "--format"),
    out: str = typer.Option(..., "--out"),
    overwrite: bool = typer.Option(False, "--overwrite"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    emit_success(
        "transcript download",
        {
            "status": "not_implemented",
            "meeting_id": meeting_id,
            "format": format_value,
            "out": out,
            "overwrite": overwrite,
        },
        as_json=json_output,
    )


@transcript_app.command("batch")
def batch_transcripts(
    from_value: str = typer.Option(..., "--from"),
    to_value: str = typer.Option(..., "--to"),
    download_dir: str = typer.Option(..., "--download-dir"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    emit_success(
        "transcript batch",
        {
            "status": "not_implemented",
            "from": from_value,
            "to": to_value,
            "download_dir": download_dir,
        },
        as_json=json_output,
    )

