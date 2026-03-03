from __future__ import annotations

from typing import Any

import typer

from webex_cli.commands.common import (
    build_client,
    emit_success,
    fail,
    fetch_all_pages,
    handle_unexpected,
    resolve_effective_timezone,
    validate_id,
)
from webex_cli.errors import CliError, DomainCode
from webex_cli.utils.time import parse_time_range

meeting_app = typer.Typer(help="Meeting commands")


@meeting_app.command("list")
def list_meetings(
    from_value: str = typer.Option(..., "--from"),
    to_value: str = typer.Option(..., "--to"),
    participant: str = typer.Option("me", "--participant"),
    tz: str | None = typer.Option(None, "--tz"),
    page_size: int = typer.Option(50, "--page-size"),
    page_token: str | None = typer.Option(None, "--page-token"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    command = "meeting list"
    try:
        if participant != "me":
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "`--participant` only supports `me` in Phase 1.",
                details={"participant": participant},
            )
        if page_size < 1 or page_size > 200:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "`--page-size` must be between 1 and 200.",
                details={"page_size": page_size},
            )
        from_utc, to_utc = parse_time_range(from_value, to_value, resolve_effective_timezone(tz))
        client = build_client()
        items, warnings = fetch_all_pages(
            lambda token: client.list_meetings(
                from_utc=from_utc,
                to_utc=to_utc,
                participant=participant,
                page_size=page_size,
                page_token=token,
            ),
            start_token=page_token,
        )
        normalized: list[dict[str, Any]] = []
        for item in items:
            host_emails = item.get("hostEmails") or item.get("host_emails") or []
            normalized.append(
                {
                    "meeting_id": item.get("id") or item.get("meetingId"),
                    "meeting_uuid": item.get("meetingUuid") or item.get("meetingUUID"),
                    "title": item.get("title") or item.get("topic") or "",
                    "started_at": item.get("start") or item.get("startedAt") or item.get("started_at"),
                    "ended_at": item.get("end") or item.get("endedAt") or item.get("ended_at"),
                    "host_email": host_emails[0] if host_emails else None,
                }
            )
        normalized.sort(key=lambda i: i.get("started_at") or "", reverse=True)
        emit_success(
            command,
            {"items": normalized, "next_page_token": None},
            as_json=json_output,
            warnings=warnings,
        )
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@meeting_app.command("get")
def get_meeting(meeting_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    command = "meeting get"
    try:
        meeting_id = validate_id(meeting_id, "meeting_id")
        client = build_client()
        item = client.get_meeting(meeting_id)
        data = {
            "meeting_id": item.get("id") or meeting_id,
            "join_url": item.get("webLink") or item.get("joinWebUrl") or item.get("joinUrl"),
            "transcript_hint": (
                "ready"
                if item.get("hasTranscript") is True
                else "unknown"
            ),
            "recording_hint": (
                "ready"
                if item.get("hasRecording") is True
                else "unknown"
            ),
            "raw": item,
        }
        emit_success(command, data, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@meeting_app.command("join-url")
def join_url(meeting_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    command = "meeting join-url"
    try:
        meeting_id = validate_id(meeting_id, "meeting_id")
        client = build_client()
        item = client.get_meeting_join_url(meeting_id)
        url = item.get("webLink") or item.get("joinWebUrl") or item.get("joinUrl")
        if not url:
            raise CliError(
                DomainCode.NOT_FOUND,
                "Join URL not available for meeting.",
                details={"meeting_id": meeting_id},
            )
        emit_success(command, {"meeting_id": meeting_id, "join_url": url}, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)
