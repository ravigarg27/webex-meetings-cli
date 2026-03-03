from __future__ import annotations

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
    resolve_effective_timezone,
    validate_id,
)
from webex_cli.errors import CliError, DomainCode
from webex_cli.models import RecordingStatus, map_recording_status
from webex_cli.utils.files import atomic_write_bytes
from webex_cli.utils.time import parse_time_range

recording_app = typer.Typer(help="Recording commands")


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


def _normalize_recording(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "recording_id": item.get("id") or item.get("recordingId"),
        "meeting_id": item.get("meetingId") or item.get("meeting_id"),
        "occurrence_id": item.get("occurrenceId") or item.get("occurrence_id"),
        "started_at": item.get("createTime") or item.get("startedAt") or item.get("started_at"),
        "duration_seconds": item.get("durationSeconds") or item.get("duration"),
        "size_bytes": item.get("sizeBytes") or item.get("size"),
        "downloadable": bool(item.get("downloadUrl") or item.get("download_url")),
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


@recording_app.command("list")
def list_recordings(
    from_value: str = typer.Option(..., "--from"),
    to_value: str = typer.Option(..., "--to"),
    participant: str = typer.Option("me", "--participant", hidden=True),
    tz: str | None = typer.Option(None, "--tz"),
    page_size: int = typer.Option(50, "--page-size"),
    page_token: str | None = typer.Option(None, "--page-token"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    command = "recording list"
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
        with managed_client(client_factory=build_client) as client:
            items, warnings = fetch_all_pages(
                lambda token: client.list_recordings(
                    from_utc=from_utc,
                    to_utc=to_utc,
                    participant=participant,
                    page_size=page_size,
                    page_token=token,
                ),
                start_token=page_token,
            )
        normalized = [_normalize_recording(item) for item in items]
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


@recording_app.command("status")
def status_recording(
    meeting_id: str,
    recording_id: str | None = typer.Option(None, "--recording-id"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    command = "recording status"
    try:
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


@recording_app.command("download")
def download_recording(
    meeting_id: str,
    out: str = typer.Option(..., "--out"),
    recording_id: str | None = typer.Option(None, "--recording-id"),
    quality: str = typer.Option("best", "--quality"),
    overwrite: bool = typer.Option(False, "--overwrite"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    command = "recording download"
    try:
        meeting_id = validate_id(meeting_id, "meeting_id")
        if recording_id:
            recording_id = validate_id(recording_id, "recording_id")
        if quality not in {"best", "high", "medium"}:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "`--quality` must be one of: best, high, medium.",
                details={"quality": quality},
            )
        with managed_client(client_factory=build_client) as client:
            selected = _resolve_recording(client, meeting_id, recording_id)
            if selected is None:
                raise CliError(DomainCode.NOT_FOUND, "No recording found for meeting.", details={"meeting_id": meeting_id})
            selected_id = selected.get("id") or selected.get("recordingId")
            if not selected_id:
                raise CliError(DomainCode.NOT_FOUND, "Recording ID missing from upstream payload.")
            content, actual_quality = client.download_recording(str(selected_id), quality)
        output_path = Path(out)
        atomic_write_bytes(output_path, content, overwrite=overwrite)
        warnings: list[str] = []
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
