from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import typer

from webex_cli.client.api import WebexApiClient
from webex_cli.commands.common import (
    build_client,
    emit_success,
    fail,
    fetch_all_pages,
    handle_unexpected,
    managed_client,
    profile_scope,
    resolve_effective_timezone,
    validate_id,
)
from webex_cli.errors import CliError, DomainCode
from webex_cli.models import RecordingStatus, map_recording_status
from webex_cli.search import collect_pages, evaluate_filter, match_query, primary_sort_field, sort_items
from webex_cli.utils.files import checksum_from_metadata
from webex_cli.utils.time import parse_time_range

recording_app = typer.Typer(help="List and download Webex meeting recordings.")
DEFAULT_LAST_LOOKBACK_DAYS = 30
DEFAULT_SEARCH_LIMIT = 50
DEFAULT_SEARCH_MAX_PAGES = 5
SEARCH_PAGE_SIZE = 200
RECORDING_SEARCH_SCHEMA = {
    "recording_id": "string",
    "meeting_id": "string",
    "occurrence_id": "string",
    "title": "string",
    "started_at": "datetime",
    "duration_seconds": "int",
    "size_bytes": "int",
    "downloadable": "bool",
    "score": "int",
}


def _status_from_exception(exc: CliError) -> RecordingStatus | None:
    if exc.code == DomainCode.NOT_FOUND:
        return RecordingStatus.NOT_FOUND
    if exc.code == DomainCode.RECORDING_DISABLED:
        return RecordingStatus.RECORDING_DISABLED
    if exc.code == DomainCode.NO_ACCESS:
        upstream_code = (exc.details or {}).get("upstream_code")
        if upstream_code in {"FEATURE_DISABLED", "ORG_POLICY_RESTRICTED"}:
            return RecordingStatus.RECORDING_DISABLED
        return RecordingStatus.NO_ACCESS
    return None


def _format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return ""
    minutes = int(seconds) // 60
    if minutes < 60:
        return f"{minutes}m"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m" if mins else f"{hours}h"


def _format_size(size_bytes: int | float | None) -> str:
    if size_bytes is None:
        return ""
    b = int(size_bytes)
    for unit, threshold in [("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)]:
        if b >= threshold:
            value = b / threshold
            return f"{value:.1f} {unit}" if value < 100 else f"{int(value)} {unit}"
    return f"{b} B"


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _first_present(item: dict[str, Any], keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if key in item and item.get(key) is not None:
            return item.get(key)
    return None


def _normalize_recording(item: dict[str, Any]) -> dict[str, Any]:
    duration_seconds = _to_int(_first_present(item, ("durationSeconds", "duration")))
    size_bytes = _to_int(_first_present(item, ("sizeBytes", "size")))
    links = item.get("temporaryDirectDownloadLinks")
    has_temp_links = isinstance(links, dict) and bool(links)
    return {
        "recording_id": item.get("id") or item.get("recordingId"),
        "meeting_id": item.get("meetingId") or item.get("meeting_id"),
        "occurrence_id": item.get("occurrenceId") or item.get("occurrence_id"),
        "started_at": item.get("createTime") or item.get("startedAt") or item.get("started_at"),
        "duration_seconds": duration_seconds,
        "size_bytes": size_bytes,
        "downloadable": bool(item.get("downloadUrl") or item.get("download_url") or has_temp_links),
    }


def _normalize_recording_search_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_recording(item)
    normalized["title"] = str(item.get("topic") or item.get("title") or normalized["recording_id"] or "")
    return normalized


def _resolve_search_window(from_value: str | None, to_value: str | None, tz: object | None) -> tuple[str, str]:
    if not isinstance(from_value, str):
        from_value = None
    if not isinstance(to_value, str):
        to_value = None
    now = datetime.now(timezone.utc)
    if from_value is None:
        from_value = (now - timedelta(days=DEFAULT_LAST_LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if to_value is None:
        to_value = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    effective_tz = tz if isinstance(tz, str) else None
    return parse_time_range(from_value, to_value, resolve_effective_timezone(effective_tz))


def _recording_search_text(item: dict[str, Any]) -> list[object]:
    return [
        item.get("title"),
        item.get("recording_id"),
        item.get("meeting_id"),
    ]


def _recording_search_result(item: dict[str, Any], *, snippet: str, score: int, sort_field: str) -> dict[str, Any]:
    return {
        "resource_type": "recording",
        "resource_id": item.get("recording_id"),
        "title": item.get("title") or "",
        "snippet": snippet,
        "score": score,
        "sort_key": item.get(sort_field),
    }


def _status_from_recording_item(item: dict[str, Any]) -> tuple[RecordingStatus, list[str]]:
    warnings: list[str] = []
    raw_status = item.get("status") or item.get("state")
    if raw_status is None:
        if item.get("downloadUrl") or item.get("download_url"):
            return RecordingStatus.READY, warnings
        return RecordingStatus.PROCESSING, warnings

    status_value = map_recording_status(raw_status)
    known = {
        "processing",
        "in_progress",
        "ready",
        "available",
        "failed",
        "error",
        "no_access",
        "forbidden",
        "not_found",
        "missing",
        "not_recorded",
        "disabled",
        "recording_disabled",
    }
    if status_value == RecordingStatus.FAILED and str(raw_status).lower() not in known:
        warnings.append("UNMAPPED_RECORDING_STATUS")
    return status_value, warnings


def _resolve_recording(client: WebexApiClient, meeting_id: str, recording_id: str | None) -> dict[str, Any] | None:
    if recording_id:
        item = client.get_recording(recording_id)
        item_meeting_id = item.get("meetingId") or item.get("meeting_id")
        if item_meeting_id and str(item_meeting_id) != meeting_id:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Provided recording does not belong to the provided meeting.",
                details={"meeting_id": meeting_id, "recording_id": recording_id, "recording_meeting_id": item_meeting_id},
            )
        return item
    records = client.list_recordings_for_meeting(meeting_id)
    if len(records) == 0:
        return None
    if len(records) > 1:
        raise CliError(
            DomainCode.AMBIGUOUS_RECORDING,
            "Multiple recordings found. Pass --recording-id.",
            details={"meeting_id": meeting_id, "count": len(records)},
        )
    return records[0]


@recording_app.command("list", help="List recordings within a date range or the last N recordings.")
def list_recordings(
    from_value: str | None = typer.Option(None, "--from", help="Start date (YYYY-MM-DD or ISO 8601). Required unless --last is used."),
    to_value: str | None = typer.Option(None, "--to", help="End date (YYYY-MM-DD or ISO 8601). Required unless --last is used."),
    last: int | None = typer.Option(None, "--last", help="Return the N most recent recordings (lookback: 30 days)."),
    tz: str | None = typer.Option(None, "--tz", help="Timezone for interpreting bare dates (e.g. America/New_York)."),
    page_size: int = typer.Option(50, "--page-size", help="Number of results per API page (1-200)."),
    page_token: str | None = typer.Option(None, "--page-token", help="Resume from a page token returned by a previous call."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "recording list"
    try:
        with profile_scope(None):
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
                next_page_token: str | None
                if page_token:
                    items, next_page_token = client.list_recordings(
                        from_utc=from_utc,
                        to_utc=to_utc,
                        page_size=page_size,
                        page_token=page_token,
                    )
                    warnings = []
                else:
                    items, warnings = fetch_all_pages(
                        lambda token: client.list_recordings(
                            from_utc=from_utc,
                            to_utc=to_utc,
                            page_size=page_size,
                            page_token=token,
                        ),
                    )
                    next_page_token = None
            normalized = [_normalize_recording(item) for item in items]
            normalized.sort(key=lambda i: i.get("started_at") or "", reverse=True)
            if last is not None:
                normalized = normalized[:last]
            emit_success(
                command,
                {"items": normalized, "next_page_token": next_page_token},
                as_json=json_output,
                warnings=warnings,
            )
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@recording_app.command("search", help="Search recordings by text, filters, and sorting.")
def search_recordings(
    query: str = typer.Option(..., "--query", help="Search text."),
    from_value: str | None = typer.Option(None, "--from", help="Start date (YYYY-MM-DD or ISO 8601). Defaults to 30 days ago."),
    to_value: str | None = typer.Option(None, "--to", help="End date (YYYY-MM-DD or ISO 8601). Defaults to now."),
    tz: str | None = typer.Option(None, "--tz", help="Timezone for interpreting bare dates (e.g. America/New_York)."),
    filter_value: str | None = typer.Option(None, "--filter", help="Structured filter expression."),
    sort_value: str | None = typer.Option(None, "--sort", help="Sort fields, e.g. score:desc,started_at:desc."),
    limit: int = typer.Option(DEFAULT_SEARCH_LIMIT, "--limit", help="Maximum number of rows to return."),
    max_pages: int = typer.Option(DEFAULT_SEARCH_MAX_PAGES, "--max-pages", help="Maximum number of upstream pages to fetch."),
    page_token: str | None = typer.Option(None, "--page-token", help="Resume from a page token returned by a previous call."),
    case_sensitive: bool = typer.Option(False, "--case-sensitive", help="Use case-sensitive query and filter evaluation."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "recording search"
    try:
        with profile_scope(None):
            filter_value = filter_value if isinstance(filter_value, str) else None
            sort_value = sort_value if isinstance(sort_value, str) else None
            page_token = page_token if isinstance(page_token, str) else None
            limit = limit if isinstance(limit, int) and not isinstance(limit, bool) else DEFAULT_SEARCH_LIMIT
            max_pages = max_pages if isinstance(max_pages, int) and not isinstance(max_pages, bool) else DEFAULT_SEARCH_MAX_PAGES
            case_sensitive = case_sensitive if isinstance(case_sensitive, bool) else False
            json_output = json_output if isinstance(json_output, bool) else False
            if not query.strip():
                raise CliError(DomainCode.VALIDATION_ERROR, "`--query` must not be empty.")
            if limit < 1:
                raise CliError(DomainCode.VALIDATION_ERROR, "`--limit` must be a positive integer.", details={"limit": limit})
            sort_field = primary_sort_field(sort_value, default_field="score")
            effective_sort = sort_value if sort_value and sort_value.strip() else "score:desc,started_at:desc"
            from_utc, to_utc = _resolve_search_window(from_value, to_value, tz)
            with managed_client(client_factory=build_client) as client:
                items, next_page_token, warnings = collect_pages(
                    lambda token: client.list_recordings(
                        from_utc=from_utc,
                        to_utc=to_utc,
                        page_size=SEARCH_PAGE_SIZE,
                        page_token=token,
                    ),
                    start_token=page_token,
                    max_pages=max_pages,
                )

            matches: list[dict[str, Any]] = []
            for item in items:
                normalized = _normalize_recording_search_item(item)
                matched, score, snippet = match_query(query, _recording_search_text(normalized), case_sensitive=case_sensitive)
                if not matched:
                    continue
                normalized["score"] = score
                if not evaluate_filter(filter_value, normalized, RECORDING_SEARCH_SCHEMA, case_sensitive=case_sensitive):
                    continue
                normalized["snippet"] = snippet
                matches.append(normalized)

            sorted_matches = sort_items(matches, effective_sort, RECORDING_SEARCH_SCHEMA, tie_breaker_field="recording_id")
            result_items = [
                _recording_search_result(item, snippet=str(item.get("snippet") or ""), score=int(item.get("score") or 0), sort_field=sort_field)
                for item in sorted_matches[:limit]
            ]
            emit_success(
                command,
                {"items": result_items, "next_page_token": next_page_token},
                as_json=json_output,
                warnings=warnings,
            )
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@recording_app.command("status", help="Check whether a recording is available for a meeting.")
def status_recording(
    meeting_id: str,
    recording_id: str | None = typer.Option(None, "--recording-id", help="Specific recording ID, required if the meeting has multiple recordings."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "recording status"
    try:
        with profile_scope(None):
            meeting_id = validate_id(meeting_id, "meeting_id")
            if recording_id:
                recording_id = validate_id(recording_id, "recording_id")
            with managed_client(client_factory=build_client) as client:
                try:
                    item = _resolve_recording(client, meeting_id, recording_id)
                except CliError as exc:
                    mapped = _status_from_exception(exc)
                    if mapped is not None:
                        emit_success(
                            command,
                            {"meeting_id": meeting_id, "recording_id": recording_id, "status": mapped.value},
                            as_json=json_output,
                        )
                        return
                    raise
            if item is None:
                emit_success(
                    command,
                    {"meeting_id": meeting_id, "recording_id": recording_id, "status": RecordingStatus.NOT_RECORDED.value},
                    as_json=json_output,
                )
                return
            status_value, warnings = _status_from_recording_item(item)
            emit_success(
                command,
                {
                    "meeting_id": meeting_id,
                    "recording_id": item.get("id") or recording_id,
                    "status": status_value.value,
                },
                as_json=json_output,
                warnings=warnings,
            )
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@recording_app.command("download", help="Download a recording to a file.")
def download_recording(
    meeting_id: str,
    out: str = typer.Option(..., "--out", help="Output file path."),
    recording_id: str | None = typer.Option(None, "--recording-id", help="Specific recording ID, required if the meeting has multiple recordings."),
    quality: str = typer.Option("best", "--quality", help="Preferred video quality: best (default), high, or medium. Falls back to the next available quality."),
    verify_checksum: bool = typer.Option(
        False,
        "--verify-checksum/--no-verify-checksum",
        help="Verify file checksum when upstream metadata provides one.",
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite the output file if it already exists."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "recording download"
    try:
        with profile_scope(None):
            meeting_id = validate_id(meeting_id, "meeting_id")
            if recording_id:
                recording_id = validate_id(recording_id, "recording_id")
            if quality not in {"best", "high", "medium"}:
                raise CliError(
                    DomainCode.VALIDATION_ERROR,
                    "`--quality` must be one of: best, high, medium.",
                    details={"quality": quality},
                )
            output_path = Path(out)
            warnings: list[str] = []
            with managed_client(client_factory=build_client) as client:
                selected = _resolve_recording(client, meeting_id, recording_id)
                if selected is None:
                    raise CliError(DomainCode.NOT_FOUND, "No recording found for meeting.", details={"meeting_id": meeting_id})
                selected_id = selected.get("id") or selected.get("recordingId")
                if not selected_id:
                    raise CliError(DomainCode.NOT_FOUND, "Recording ID missing from upstream payload.")
                checksum_meta: tuple[str, str] | None = None
                if verify_checksum:
                    checksum_meta = checksum_from_metadata(selected)
                    if checksum_meta is None:
                        warnings.append("CHECKSUM_METADATA_MISSING")
                actual_quality = client.download_recording_to_file(
                    str(selected_id),
                    quality,
                    output_path,
                    overwrite=overwrite,
                    checksum=checksum_meta,
                )
            if actual_quality != quality:
                warnings.append("QUALITY_FALLBACK")
            emit_success(
                command,
                {
                    "meeting_id": meeting_id,
                    "recording_id": str(selected_id),
                    "quality": actual_quality,
                    "output_path": str(output_path),
                },
                as_json=json_output,
                warnings=warnings,
            )
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)
