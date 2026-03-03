from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
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
from webex_cli.models import TranscriptStatus, map_transcript_status
from webex_cli.utils.files import atomic_write_bytes, sanitize_filename
from webex_cli.utils.time import parse_time_range

transcript_app = typer.Typer(help="Download and monitor Webex meeting transcripts.")


def _status_from_exception(exc: CliError) -> TranscriptStatus | None:
    if exc.code == DomainCode.NOT_FOUND:
        return TranscriptStatus.NOT_FOUND
    if exc.code == DomainCode.TRANSCRIPT_DISABLED:
        return TranscriptStatus.TRANSCRIPT_DISABLED
    if exc.code == DomainCode.NO_ACCESS:
        upstream_code = (exc.details or {}).get("upstream_code")
        if upstream_code in {"FEATURE_DISABLED", "ORG_POLICY_RESTRICTED"}:
            return TranscriptStatus.TRANSCRIPT_DISABLED
        return TranscriptStatus.NO_ACCESS
    return None



def _normalize_get_format(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "txt":
        return "text"
    if normalized in {"text", "json"}:
        return normalized
    raise CliError(
        DomainCode.VALIDATION_ERROR,
        "`--format` must be one of: text, txt, json.",
        details={"format": value},
    )


def _normalize_download_format(value: str) -> tuple[str, str]:
    normalized = value.strip().lower()
    if normalized in {"text", "txt"}:
        return ("text", "txt")
    if normalized in {"vtt", "json"}:
        return (normalized, normalized)
    raise CliError(
        DomainCode.VALIDATION_ERROR,
        "`--format` must be one of: txt, text, vtt, json.",
        details={"format": value},
    )


def _parse_iso_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _compact_utc(value: str | None) -> str:
    dt = _parse_iso_utc(value)
    if dt is None:
        return "unknown"
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _canonical_start_utc(meeting: dict[str, Any]) -> str:
    raw = meeting.get("start") or meeting.get("startedAt") or meeting.get("started_at")
    if not raw:
        return ""
    dt = _parse_iso_utc(raw if isinstance(raw, str) else str(raw))
    if dt is None:
        return str(raw)
    return dt.isoformat().replace("+00:00", "Z")


def _batch_filename(meeting: dict[str, Any], format_value: str, artifact_id: str | None, download_url: str | None) -> str:
    meeting_id = str(meeting.get("id") or meeting.get("meetingId") or "meeting")
    start_utc = _compact_utc(meeting.get("start") or meeting.get("startedAt") or meeting.get("started_at"))
    if artifact_id:
        suffix = artifact_id
    else:
        canonical = f"{meeting_id}|{_canonical_start_utc(meeting)}|{download_url or ''}"
        suffix = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    stem = sanitize_filename(f"{meeting_id}_{start_utc}_{suffix}")
    return f"{stem}.{format_value}"


def _read_transcript_status(client: WebexApiClient, meeting_id: str) -> tuple[TranscriptStatus, dict[str, Any], list[str]]:
    warnings: list[str] = []
    try:
        items = client.list_transcripts(meeting_id)
    except CliError as exc:
        mapped = _status_from_exception(exc)
        if mapped is None:
            raise
        return mapped, {"meeting_id": meeting_id}, warnings
    if not items:
        return TranscriptStatus.NOT_FOUND, {"meeting_id": meeting_id}, warnings
    transcript = items[0]
    raw_status = transcript.get("status") or transcript.get("state")
    if raw_status:
        status = map_transcript_status(raw_status)
        if status == TranscriptStatus.FAILED:
            known = {
                "processing", "in_progress", "ready", "available",
                "failed", "error", "no_access", "forbidden",
                "not_found", "missing", "not_recorded",
                "disabled", "transcript_disabled",
            }
            if str(raw_status).lower() not in known:
                warnings.append("UNMAPPED_TRANSCRIPT_STATUS")
    else:
        status = TranscriptStatus.READY
    transcript["meeting_id"] = meeting_id
    return status, transcript, warnings


def _resolve_transcript_id(client: WebexApiClient, meeting_id: str) -> str:
    items = client.list_transcripts(meeting_id)
    if not items:
        raise CliError(
            DomainCode.NOT_FOUND,
            "No transcript found for meeting.",
            details={"meeting_id": meeting_id},
        )
    transcript_id = items[0].get("id")
    if not transcript_id:
        raise CliError(
            DomainCode.NOT_FOUND,
            "Transcript ID missing from upstream payload.",
            details={"meeting_id": meeting_id},
        )
    return str(transcript_id)


@transcript_app.command("status", help="Check whether a transcript is available for a meeting.")
def status(
    meeting_id: str,
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript status"
    try:
        meeting_id = validate_id(meeting_id, "meeting_id")
        with managed_client(client_factory=build_client) as client:
            transcript_status, payload, warnings = _read_transcript_status(client, meeting_id)
        emit_success(
            command,
            {
                "meeting_id": meeting_id,
                "status": transcript_status.value,
                "updated_at": payload.get("updatedAt") or payload.get("updated_at"),
                "reason": payload.get("reason") or payload.get("message"),
            },
            as_json=json_output,
            warnings=warnings,
        )
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@transcript_app.command("get", help="Print transcript content to stdout.")
def get_transcript(
    meeting_id: str,
    format_value: str = typer.Option("text", "--format", help="Output format: text/txt (default) or json."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript get"
    try:
        meeting_id = validate_id(meeting_id, "meeting_id")
        format_value = _normalize_get_format(format_value)
        with managed_client(client_factory=build_client) as client:
            transcript_id = _resolve_transcript_id(client, meeting_id)
            content_bytes = client.download_transcript(transcript_id, format_value)
        content = content_bytes.decode("utf-8")
        if format_value == "json":
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                pass
        emit_success(
            command,
            {"meeting_id": meeting_id, "format": format_value, "content": content},
            as_json=json_output,
        )
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@transcript_app.command("wait", help="Block until a transcript is ready, or until the timeout is reached.")
def wait_transcript(
    meeting_id: str,
    timeout: int = typer.Option(600, "--timeout", help="Maximum seconds to wait before giving up. Default: 600."),
    interval: int = typer.Option(10, "--interval", help="Seconds between status checks. Default: 10."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript wait"
    try:
        meeting_id = validate_id(meeting_id, "meeting_id")
        if timeout <= 0 or interval <= 0:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "`--timeout` and `--interval` must be positive integers.",
                details={"timeout": timeout, "interval": interval},
            )
        with managed_client(client_factory=build_client) as client:
            started = time.time()
            warnings: list[str] = []
            while True:
                current, payload, status_warnings = _read_transcript_status(client, meeting_id)
                warnings.extend(status_warnings)
                if current == TranscriptStatus.PROCESSING:
                    if (time.time() - started) >= timeout:
                        raise CliError(
                            DomainCode.ARTIFACT_NOT_READY,
                            "Transcript wait timed out.",
                            details={"meeting_id": meeting_id, "timeout": timeout},
                        )
                    if not json_output:
                        elapsed = int(time.time() - started)
                        typer.echo(
                            f"Transcript still processing — next check in {interval}s ({elapsed}s elapsed)...",
                            err=True,
                        )
                    time.sleep(interval)
                    continue
                if current == TranscriptStatus.READY:
                    emit_success(
                        command,
                        {"meeting_id": meeting_id, "status": current.value, "updated_at": payload.get("updatedAt")},
                        as_json=json_output,
                        warnings=list(dict.fromkeys(warnings)),
                    )
                    return
                if current == TranscriptStatus.FAILED:
                    raise CliError(
                        DomainCode.INTERNAL_ERROR,
                        "Transcript processing failed.",
                        details={"meeting_id": meeting_id},
                    )
                if current == TranscriptStatus.NO_ACCESS:
                    raise CliError(DomainCode.NO_ACCESS, "No access to transcript.", details={"meeting_id": meeting_id})
                if current == TranscriptStatus.TRANSCRIPT_DISABLED:
                    raise CliError(
                        DomainCode.TRANSCRIPT_DISABLED,
                        "Transcript feature is disabled for this org/site.",
                        details={"meeting_id": meeting_id},
                    )
                # not_found and not_recorded map to NOT_FOUND contract
                raise CliError(DomainCode.NOT_FOUND, "Transcript not found.", details={"meeting_id": meeting_id})
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@transcript_app.command("download", help="Save a transcript to a file.")
def download_transcript(
    meeting_id: str,
    format_value: str = typer.Option(..., "--format", help="File format: txt (default), vtt, or json."),
    out: str = typer.Option(..., "--out", help="Output file path."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite the file if it already exists."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript download"
    try:
        meeting_id = validate_id(meeting_id, "meeting_id")
        api_format, output_format = _normalize_download_format(format_value)
        with managed_client(client_factory=build_client) as client:
            transcript_id = _resolve_transcript_id(client, meeting_id)
            data_bytes = client.download_transcript(transcript_id, api_format)
        output_path = Path(out)
        atomic_write_bytes(output_path, data_bytes, overwrite=overwrite)
        emit_success(
            command,
            {"meeting_id": meeting_id, "format": output_format, "output_path": str(output_path)},
            as_json=json_output,
        )
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@transcript_app.command("batch", help="Download all available transcripts for meetings in a date range.")
def batch_transcripts(
    from_value: str = typer.Option(..., "--from", help="Start of the date range. Accepts YYYY-MM-DD or ISO 8601."),
    to_value: str = typer.Option(..., "--to", help="End of the date range. Accepts YYYY-MM-DD or ISO 8601."),
    download_dir: str = typer.Option(..., "--download-dir", help="Directory to save transcript files."),
    tz: str | None = typer.Option(None, "--tz", help="Timezone for interpreting bare dates (e.g. America/New_York)."),
    format_value: str = typer.Option("txt", "--format", help="File format for all downloads: txt (default), vtt, or json."),
    continue_on_error: bool = typer.Option(
        True,
        "--continue-on-error/--fail-fast",
        help="Continue processing remaining meetings after a failure, or stop immediately.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript batch"
    try:
        api_format, output_format = _normalize_download_format(format_value)
        continue_mode = continue_on_error

        from_utc, to_utc = parse_time_range(from_value, to_value, resolve_effective_timezone(tz))
        with managed_client(client_factory=build_client) as client:
            meetings, warnings = fetch_all_pages(
                lambda token: client.list_meetings(
                    from_utc=from_utc,
                    to_utc=to_utc,
                    page_size=50,
                    page_token=token,
                )
            )
            target_dir = Path(download_dir)
            target_dir.mkdir(parents=True, exist_ok=True)

            results: list[dict[str, Any]] = []
            success = 0
            skipped = 0
            failed = 0
            total = len(meetings)
            for index, meeting in enumerate(meetings, start=1):
                meeting_id = str(meeting.get("id") or meeting.get("meetingId") or "")
                if not json_output:
                    typer.echo(f"[{index}/{total}] processing meeting_id={meeting_id or 'unknown'}", err=True)
                if not meeting_id:
                    skipped += 1
                    results.append(
                        {
                            "meeting_id": None,
                            "status": "skipped",
                            "output_path": None,
                            "error_code": "NOT_FOUND",
                            "error_message": "Meeting missing id.",
                        }
                    )
                    continue
                try:
                    status_value, _, _ = _read_transcript_status(client, meeting_id)
                    if status_value != TranscriptStatus.READY:
                        if status_value == TranscriptStatus.FAILED:
                            failed += 1
                            results.append(
                                {
                                    "meeting_id": meeting_id,
                                    "status": "failed",
                                    "output_path": None,
                                    "error_code": DomainCode.INTERNAL_ERROR.value,
                                    "error_message": "Transcript processing failed.",
                                }
                            )
                            if not continue_mode:
                                raise CliError(
                                    DomainCode.INTERNAL_ERROR,
                                    "Transcript processing failed.",
                                    details={"meeting_id": meeting_id},
                                )
                            continue
                        skipped += 1
                        results.append(
                            {
                                "meeting_id": meeting_id,
                                "status": "skipped",
                                "output_path": None,
                                "error_code": None,
                                "error_message": f"Transcript status is {status_value.value}.",
                            }
                        )
                        continue

                    transcript_id = _resolve_transcript_id(client, meeting_id)
                    content = client.download_transcript(transcript_id, api_format)
                    artifact_id = transcript_id
                    download_url = None
                    filename = _batch_filename(meeting, output_format, artifact_id=artifact_id, download_url=download_url)
                    out_path = target_dir / filename
                    atomic_write_bytes(out_path, content, overwrite=False)
                    success += 1
                    results.append(
                        {
                            "meeting_id": meeting_id,
                            "status": "success",
                            "output_path": str(out_path),
                            "error_code": None,
                            "error_message": None,
                        }
                    )
                except CliError as exc:
                    if exc.code == DomainCode.OVERWRITE_CONFLICT:
                        skipped += 1
                        results.append(
                            {
                                "meeting_id": meeting_id,
                                "status": "skipped",
                                "output_path": None,
                                "error_code": exc.code.value,
                                "error_message": exc.message,
                            }
                        )
                        if not continue_mode:
                            raise
                        continue
                    failed += 1
                    results.append(
                        {
                            "meeting_id": meeting_id,
                            "status": "failed",
                            "output_path": None,
                            "error_code": exc.code.value,
                            "error_message": exc.message,
                        }
                    )
                    if not continue_mode:
                        raise

            emit_success(
                command,
                {
                    "total_meetings": len(meetings),
                    "success": success,
                    "skipped": skipped,
                    "failed": failed,
                    "results": results,
                },
                as_json=json_output,
                warnings=warnings,
            )
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)
