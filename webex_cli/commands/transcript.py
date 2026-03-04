from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import hashlib
import json
import threading
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
    profile_scope,
    resolve_effective_timezone,
    validate_id,
)
from webex_cli.errors import CliError, DomainCode
from webex_cli.models import TranscriptStatus, map_transcript_status
from webex_cli.utils.files import atomic_write_bytes, checksum_from_metadata, compute_checksum, sanitize_filename
from webex_cli.utils.time import parse_time_range

transcript_app = typer.Typer(help="Download and monitor Webex meeting transcripts.")
DEFAULT_BATCH_CONCURRENCY = 4
MIN_BATCH_CONCURRENCY = 1
MAX_BATCH_CONCURRENCY = 16
_THROTTLE_BASE_DELAY_SECONDS = 0.5
_THROTTLE_MAX_DELAY_SECONDS = 5.0


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
        has_download_reference = bool(transcript.get("downloadUrl") or transcript.get("download_url"))
        status = TranscriptStatus.READY if has_download_reference else TranscriptStatus.PROCESSING
        warnings.append("TRANSCRIPT_STATUS_MISSING")
    transcript["meeting_id"] = meeting_id
    return status, transcript, warnings


class _AdaptiveThrottle:
    def __init__(self) -> None:
        self._delay_seconds = 0.0
        self._lock = threading.Lock()
        self.applied = False

    def wait(self) -> None:
        with self._lock:
            delay = self._delay_seconds
        if delay > 0:
            self.applied = True
            time.sleep(delay)

    def on_success(self) -> None:
        with self._lock:
            self._delay_seconds = max(0.0, self._delay_seconds - 0.1)

    def on_throttle_signal(self) -> None:
        with self._lock:
            if self._delay_seconds <= 0:
                self._delay_seconds = _THROTTLE_BASE_DELAY_SECONDS
            else:
                self._delay_seconds = min(_THROTTLE_MAX_DELAY_SECONDS, self._delay_seconds * 1.5)


def _resolve_transcript_record(client: WebexApiClient, meeting_id: str) -> dict[str, Any]:
    items = client.list_transcripts(meeting_id)
    if not items:
        raise CliError(
            DomainCode.NOT_FOUND,
            "No transcript found for meeting.",
            details={"meeting_id": meeting_id},
        )
    transcript = items[0]
    if not transcript.get("id"):
        raise CliError(
            DomainCode.NOT_FOUND,
            "Transcript ID missing from upstream payload.",
            details={"meeting_id": meeting_id},
        )
    return transcript


def _resolve_transcript_id(client: WebexApiClient, meeting_id: str) -> str:
    transcript = _resolve_transcript_record(client, meeting_id)
    return str(transcript["id"])


def _process_batch_item(
    meeting: dict[str, Any],
    *,
    api_format: str,
    output_format: str,
    target_dir: Path,
    verify_checksum: bool,
    throttle: _AdaptiveThrottle,
) -> tuple[dict[str, Any], CliError | None]:
    meeting_id = str(meeting.get("id") or meeting.get("meetingId") or "")
    if not meeting_id:
        return (
            {
                "meeting_id": None,
                "status": "skipped",
                "output_path": None,
                "error_code": "NOT_FOUND",
                "error_message": "Meeting missing id.",
            },
            None,
        )
    try:
        with managed_client(client_factory=build_client) as worker_client:
            throttle.wait()
            status_value, _, _ = _read_transcript_status(worker_client, meeting_id)
            if status_value != TranscriptStatus.READY:
                if status_value == TranscriptStatus.FAILED:
                    terminal_error = CliError(
                        DomainCode.INTERNAL_ERROR,
                        "Transcript processing failed.",
                        details={"meeting_id": meeting_id},
                    )
                    return (
                        {
                            "meeting_id": meeting_id,
                            "status": "failed",
                            "output_path": None,
                            "error_code": terminal_error.code.value,
                            "error_message": terminal_error.message,
                        },
                        terminal_error,
                    )
                return (
                    {
                        "meeting_id": meeting_id,
                        "status": "skipped",
                        "output_path": None,
                        "error_code": None,
                        "error_message": f"Transcript status is {status_value.value}.",
                    },
                    None,
                )

            transcript = _resolve_transcript_record(worker_client, meeting_id)
            transcript_id = str(transcript["id"])
            content = worker_client.download_transcript(transcript_id, api_format)
            if verify_checksum:
                checksum_meta = checksum_from_metadata(transcript)
                if checksum_meta is not None:
                    algorithm, expected = checksum_meta
                    actual = compute_checksum(content, algorithm)
                    if actual != expected:
                        mismatch_error = CliError(
                            DomainCode.DOWNLOAD_FAILED,
                            "Downloaded transcript checksum mismatch.",
                            details={
                                "meeting_id": meeting_id,
                                "transcript_id": transcript_id,
                                "algorithm": algorithm,
                                "expected": expected,
                                "actual": actual,
                            },
                        )
                        return (
                            {
                                "meeting_id": meeting_id,
                                "status": "failed",
                                "output_path": None,
                                "error_code": mismatch_error.code.value,
                                "error_message": mismatch_error.message,
                            },
                            mismatch_error,
                        )
            filename = _batch_filename(meeting, output_format, artifact_id=transcript_id, download_url=None)
            out_path = target_dir / filename
            atomic_write_bytes(out_path, content, overwrite=False)
            throttle.on_success()
            return (
                {
                    "meeting_id": meeting_id,
                    "status": "success",
                    "output_path": str(out_path),
                    "error_code": None,
                    "error_message": None,
                },
                None,
            )
    except CliError as exc:
        if exc.code in {DomainCode.RATE_LIMITED, DomainCode.UPSTREAM_UNAVAILABLE}:
            throttle.on_throttle_signal()
        if exc.code == DomainCode.OVERWRITE_CONFLICT:
            return (
                {
                    "meeting_id": meeting_id,
                    "status": "skipped",
                    "output_path": None,
                    "error_code": exc.code.value,
                    "error_message": exc.message,
                },
                None,
            )
        return (
            {
                "meeting_id": meeting_id,
                "status": "failed",
                "output_path": None,
                "error_code": exc.code.value,
                "error_message": exc.message,
            },
            exc,
        )


@transcript_app.command("status", help="Check whether a transcript is available for a meeting.")
def status(
    meeting_id: str,
    profile: str | None = typer.Option(None, "--profile", help="Use a specific local profile for this command."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript status"
    try:
        with profile_scope(profile):
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
    except typer.Exit:
        raise
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@transcript_app.command("get", help="Print transcript content to stdout.")
def get_transcript(
    meeting_id: str,
    format_value: str = typer.Option("text", "--format", help="Output format: text/txt (default) or json."),
    profile: str | None = typer.Option(None, "--profile", help="Use a specific local profile for this command."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript get"
    try:
        with profile_scope(profile):
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
    profile: str | None = typer.Option(None, "--profile", help="Use a specific local profile for this command."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript wait"
    try:
        with profile_scope(profile):
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
    verify_checksum: bool = typer.Option(
        False,
        "--verify-checksum/--no-verify-checksum",
        help="Verify file checksum when upstream metadata provides one.",
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite the file if it already exists."),
    profile: str | None = typer.Option(None, "--profile", help="Use a specific local profile for this command."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript download"
    try:
        with profile_scope(profile):
            meeting_id = validate_id(meeting_id, "meeting_id")
            api_format, output_format = _normalize_download_format(format_value)
            with managed_client(client_factory=build_client) as client:
                transcript = _resolve_transcript_record(client, meeting_id)
                transcript_id = str(transcript["id"])
                data_bytes = client.download_transcript(transcript_id, api_format)
            warnings: list[str] = []
            if verify_checksum:
                checksum_meta = checksum_from_metadata(transcript)
                if checksum_meta is None:
                    warnings.append("CHECKSUM_METADATA_MISSING")
                else:
                    algorithm, expected = checksum_meta
                    actual = compute_checksum(data_bytes, algorithm)
                    if actual != expected:
                        raise CliError(
                            DomainCode.DOWNLOAD_FAILED,
                            "Downloaded transcript checksum mismatch.",
                            details={
                                "meeting_id": meeting_id,
                                "transcript_id": transcript_id,
                                "algorithm": algorithm,
                                "expected": expected,
                                "actual": actual,
                            },
                        )
            output_path = Path(out)
            atomic_write_bytes(output_path, data_bytes, overwrite=overwrite)
            emit_success(
                command,
                {"meeting_id": meeting_id, "format": output_format, "output_path": str(output_path)},
                as_json=json_output,
                warnings=warnings,
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
    verify_checksum: bool = typer.Option(
        False,
        "--verify-checksum/--no-verify-checksum",
        help="Verify file checksum when upstream metadata provides one.",
    ),
    concurrency: int = typer.Option(
        DEFAULT_BATCH_CONCURRENCY,
        "--concurrency",
        help=f"Batch worker concurrency ({MIN_BATCH_CONCURRENCY}-{MAX_BATCH_CONCURRENCY}).",
    ),
    profile: str | None = typer.Option(None, "--profile", help="Use a specific local profile for this command."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript batch"
    try:
        with profile_scope(profile):
            api_format, output_format = _normalize_download_format(format_value)
            continue_mode = continue_on_error
            if concurrency < MIN_BATCH_CONCURRENCY or concurrency > MAX_BATCH_CONCURRENCY:
                raise CliError(
                    DomainCode.VALIDATION_ERROR,
                    f"`--concurrency` must be between {MIN_BATCH_CONCURRENCY} and {MAX_BATCH_CONCURRENCY}.",
                    details={"concurrency": concurrency},
                )

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

                total = len(meetings)
                indexed_meetings = list(enumerate(meetings))
                results_by_index: dict[int, dict[str, Any]] = {}
                first_terminal_error: CliError | None = None
                next_to_submit = 0
                throttle = _AdaptiveThrottle()

                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    inflight: dict[Future[tuple[dict[str, Any], CliError | None]], int] = {}

                    def _submit(idx: int, meeting: dict[str, Any]) -> None:
                        if not json_output:
                            meeting_id = str(meeting.get("id") or meeting.get("meetingId") or "")
                            typer.echo(f"[{idx + 1}/{total}] processing meeting_id={meeting_id or 'unknown'}", err=True)
                        inflight[executor.submit(
                            _process_batch_item,
                            meeting,
                            api_format=api_format,
                            output_format=output_format,
                            target_dir=target_dir,
                            verify_checksum=verify_checksum,
                            throttle=throttle,
                        )] = idx

                    while next_to_submit < total and len(inflight) < concurrency:
                        idx, meeting = indexed_meetings[next_to_submit]
                        _submit(idx, meeting)
                        next_to_submit += 1

                    while inflight:
                        completed, _ = wait(inflight.keys(), return_when=FIRST_COMPLETED)
                        for future in completed:
                            idx = inflight.pop(future)
                            try:
                                result, terminal_error = future.result()
                            except Exception as exc:
                                terminal_error = CliError(
                                    DomainCode.INTERNAL_ERROR,
                                    "Unexpected batch worker error.",
                                    details={"error_type": type(exc).__name__},
                                )
                                result = {
                                    "meeting_id": str(meetings[idx].get("id") or meetings[idx].get("meetingId") or ""),
                                    "status": "failed",
                                    "output_path": None,
                                    "error_code": terminal_error.code.value,
                                    "error_message": terminal_error.message,
                                }
                            results_by_index[idx] = result
                            if terminal_error and first_terminal_error is None:
                                first_terminal_error = terminal_error

                        while (
                            continue_mode or first_terminal_error is None
                        ) and next_to_submit < total and len(inflight) < concurrency:
                            idx, meeting = indexed_meetings[next_to_submit]
                            _submit(idx, meeting)
                            next_to_submit += 1

                if not continue_mode and first_terminal_error and next_to_submit < total:
                    for idx in range(next_to_submit, total):
                        meeting = meetings[idx]
                        results_by_index[idx] = {
                            "meeting_id": str(meeting.get("id") or meeting.get("meetingId") or ""),
                            "status": "skipped",
                            "output_path": None,
                            "error_code": "FAIL_FAST_ABORTED",
                            "error_message": "Skipped due to fail-fast after first terminal failure.",
                        }

                results = [results_by_index[idx] for idx in sorted(results_by_index)]
                success = sum(1 for item in results if item.get("status") == "success")
                skipped = sum(1 for item in results if item.get("status") == "skipped")
                failed = sum(1 for item in results if item.get("status") == "failed")

                emit_success(
                    command,
                    {
                        "total_meetings": total,
                        "success": success,
                        "skipped": skipped,
                        "failed": failed,
                        "results": results,
                    },
                    as_json=json_output,
                    warnings=warnings + (["ADAPTIVE_THROTTLE_APPLIED"] if throttle.applied else []),
                )
                if not continue_mode and first_terminal_error is not None:
                    raise typer.Exit(code=first_terminal_error.exit_code)
    except typer.Exit:
        raise
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)
