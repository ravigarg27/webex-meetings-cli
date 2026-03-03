from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import typer

from webex_cli.commands.common import (
    build_client,
    emit_success,
    fail,
    fetch_all_pages,
    handle_unexpected,
    managed_client,
    resolve_effective_timezone,
    validate_id,
)
from webex_cli.errors import CliError, DomainCode
from webex_cli.utils.time import parse_time_range

meeting_app = typer.Typer(help="List and inspect Webex meetings.")

DEFAULT_LAST_LOOKBACK_DAYS = 30


def _normalize_meeting(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "meeting_id": item.get("id") or item.get("meetingId"),
        "series_id": item.get("meetingSeriesId"),
        "title": item.get("title") or item.get("topic") or "",
        "started_at": item.get("start") or item.get("startedAt") or item.get("started_at"),
        "ended_at": item.get("end") or item.get("endedAt") or item.get("ended_at"),
        "host_email": item.get("hostEmail") or item.get("host_email"),
        "host_name": item.get("hostDisplayName"),
        "site_url": item.get("siteUrl"),
    }


@meeting_app.command("list", help="List meetings within a date range or the last N meetings.")
def list_meetings(
    from_value: str | None = typer.Option(None, "--from", help="Start date (YYYY-MM-DD or ISO 8601). Required unless --last is used."),
    to_value: str | None = typer.Option(None, "--to", help="End date (YYYY-MM-DD or ISO 8601). Required unless --last is used."),
    last: int | None = typer.Option(None, "--last", help="Return the N most recent meetings (lookback: 30 days)."),
    tz: str | None = typer.Option(None, "--tz", help="Timezone for interpreting bare dates (e.g. America/New_York)."),
    page_size: int = typer.Option(50, "--page-size", help="Number of results per API page (1-200)."),
    page_token: str | None = typer.Option(None, "--page-token", help="Resume from a page token returned by a previous call."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting list"
    try:
        if last is not None and (from_value is not None or to_value is not None):
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Use either --last or --from/--to, not both.",
            )
        if last is not None:
            if last < 1:
                raise CliError(
                    DomainCode.VALIDATION_ERROR,
                    "`--last` must be a positive integer.",
                    details={"last": last},
                )
            now = datetime.now(timezone.utc)
            to_value = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            from_value = (now - timedelta(days=DEFAULT_LAST_LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if from_value is None or to_value is None:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Provide --from and --to, or use --last N.",
            )
        if page_size < 1 or page_size > 200:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "`--page-size` must be between 1 and 200.",
                details={"page_size": page_size},
            )
        from_utc, to_utc = parse_time_range(from_value, to_value, resolve_effective_timezone(tz))
        with managed_client(client_factory=build_client) as client:
            items, warnings = fetch_all_pages(
                lambda token: client.list_meetings(
                    from_utc=from_utc,
                    to_utc=to_utc,
                    page_size=page_size,
                    page_token=token,
                ),
                start_token=page_token,
            )
        normalized = [_normalize_meeting(item) for item in items]
        normalized.sort(key=lambda i: i.get("started_at") or "", reverse=True)
        if last is not None:
            normalized = normalized[:last]
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


@meeting_app.command("get", help="Fetch full details for a single meeting.")
def get_meeting(
    meeting_id: str,
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting get"
    try:
        meeting_id = validate_id(meeting_id, "meeting_id")
        with managed_client(client_factory=build_client) as client:
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


@meeting_app.command("join-url", help="Print the join URL for a meeting.")
def join_url(
    meeting_id: str,
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting join-url"
    try:
        meeting_id = validate_id(meeting_id, "meeting_id")
        with managed_client(client_factory=build_client) as client:
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
