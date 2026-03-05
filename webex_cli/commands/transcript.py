from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import hashlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import typer

from webex_cli.capabilities import capability_unavailable
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
    resolve_profile,
    validate_id,
)
from webex_cli.config.options import resolve_option
from webex_cli.errors import CliError, DomainCode
from webex_cli.models import TranscriptStatus, map_transcript_status
from webex_cli.search import collect_pages, evaluate_filter, match_query, primary_sort_field, sort_items
from webex_cli.transcript_index import TranscriptLocalIndex
from webex_cli.mutations import require_confirmation
from webex_cli.utils.files import checksum_from_metadata, sanitize_filename
from webex_cli.utils.time import parse_time_range

transcript_app = typer.Typer(help="Download and monitor Webex meeting transcripts.")
index_app = typer.Typer(help="Manage the local transcript search index.")
index_key_app = typer.Typer(help="Manage transcript index encryption keys.")
DEFAULT_BATCH_CONCURRENCY = 4
MIN_BATCH_CONCURRENCY = 1
MAX_BATCH_CONCURRENCY = 16
_THROTTLE_BASE_DELAY_SECONDS = 0.5
_THROTTLE_MAX_DELAY_SECONDS = 5.0
DEFAULT_LAST_LOOKBACK_DAYS = 30
DEFAULT_SEARCH_LIMIT = 50
DEFAULT_SEARCH_MAX_PAGES = 5
SEARCH_PAGE_SIZE = 200
UNKNOWN_SPEAKER = "(Unknown)"
TRANSCRIPT_SEARCH_SCHEMA = {
    "transcript_id": "string",
    "meeting_id": "string",
    "title": "string",
    "started_at": "datetime",
    "segment_count": "int",
    "speaker_count": "int",
    "score": "int",
}


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
            if self._delay_seconds <= 0:
                return
            self._delay_seconds = self._delay_seconds * 0.8
            if self._delay_seconds < 0.05:
                self._delay_seconds = 0.0

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


def _first_present(item: dict[str, Any], keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if key in item and item.get(key) is not None:
            return item.get(key)
    return None


def _parse_number(value: object | None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _offset_ms(segment: dict[str, Any], *, prefix: str) -> int | None:
    ms_value = _first_present(segment, (f"{prefix}OffsetMs", f"{prefix}TimeMs", f"{prefix}Ms"))
    numeric = _parse_number(ms_value)
    if numeric is not None:
        return int(numeric)

    sec_value = _first_present(segment, (f"{prefix}OffsetSeconds", f"{prefix}Seconds"))
    numeric = _parse_number(sec_value)
    if numeric is not None:
        return int(numeric * 1000)

    fallback_value = _first_present(segment, (f"{prefix}Offset", prefix))
    numeric = _parse_number(fallback_value)
    if numeric is None:
        return None
    if abs(numeric) >= 1000:
        return int(numeric)
    return int(numeric * 1000)


def _normalize_speaker(value: object | None) -> str:
    if isinstance(value, dict):
        nested = _first_present(value, ("name", "displayName", "label", "id"))
        return _normalize_speaker(nested)
    if value is None:
        return UNKNOWN_SPEAKER
    speaker = str(value).strip()
    return speaker or UNKNOWN_SPEAKER


def _extract_segment_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("segments", "items", "results", "utterances"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _load_transcript_segments(client: WebexApiClient, meeting_id: str) -> tuple[str, list[dict[str, Any]]]:
    transcript = _resolve_transcript_record(client, meeting_id)
    transcript_id = str(transcript["id"])
    try:
        payload = json.loads(client.download_transcript(transcript_id, "json").decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise CliError(
            DomainCode.UPSTREAM_UNAVAILABLE,
            "Transcript JSON payload was invalid.",
            details={"meeting_id": meeting_id, "transcript_id": transcript_id},
        ) from exc

    normalized_segments: list[dict[str, Any]] = []
    for index, segment in enumerate(_extract_segment_items(payload), start=1):
        start_offset_ms = _offset_ms(segment, prefix="start")
        end_offset_ms = _offset_ms(segment, prefix="end")
        if end_offset_ms is None and start_offset_ms is not None:
            end_offset_ms = start_offset_ms
        normalized_segments.append(
            {
                "segment_id": str(segment.get("id") or segment.get("segmentId") or f"{transcript_id}:{index}"),
                "speaker": _normalize_speaker(segment.get("speaker") or segment.get("speakerName")),
                "start_offset_ms": start_offset_ms,
                "end_offset_ms": end_offset_ms,
                "text": str(_first_present(segment, ("text", "content", "transcript", "value")) or ""),
            }
        )
    return transcript_id, normalized_segments


def _load_required_transcript_segments(client: WebexApiClient, meeting_id: str) -> tuple[str, list[dict[str, Any]]]:
    transcript_id, normalized_segments = _load_transcript_segments(client, meeting_id)
    if normalized_segments:
        return transcript_id, normalized_segments
    raise capability_unavailable(
        "TRANSCRIPT_SEGMENTS_UNAVAILABLE",
        "Transcript segment metadata is unavailable for this meeting.",
        details={"meeting_id": meeting_id, "transcript_id": transcript_id},
    )


def _speaker_matches(candidate: str, expected: str | None, *, case_sensitive: bool) -> bool:
    if expected is None:
        return True
    if case_sensitive:
        return candidate == expected
    return candidate.lower() == expected.lower()


def _segment_overlaps_window(segment: dict[str, Any], *, from_offset_ms: int | None, to_offset_ms: int | None) -> bool:
    start = segment.get("start_offset_ms")
    end = segment.get("end_offset_ms")
    if from_offset_ms is not None and end is not None and end < from_offset_ms:
        return False
    if to_offset_ms is not None and start is not None and start > to_offset_ms:
        return False
    return True


def _transcript_search_result(item: dict[str, Any], *, sort_field: str) -> dict[str, Any]:
    return {
        "resource_type": "transcript",
        "resource_id": item.get("transcript_id"),
        "title": item.get("title") or "",
        "snippet": str(item.get("snippet") or ""),
        "score": int(item.get("score") or 0),
        "sort_key": item.get(sort_field),
    }


def _local_index() -> TranscriptLocalIndex:
    return TranscriptLocalIndex(resolve_profile())


def _local_index_enabled() -> bool:
    return bool(
        resolve_option(
            None,
            "WEBEX_SEARCH_LOCAL_INDEX_ENABLED",
            "search.local_index_enabled",
            "search_local_index_enabled",
            default=False,
            value_type="bool",
        )
    )


def _local_index_stale_hours() -> int:
    return int(
        resolve_option(
            None,
            "WEBEX_SEARCH_LOCAL_INDEX_STALE_HOURS",
            "search.local_index_stale_hours",
            "search_local_index_stale_hours",
            default=6,
            value_type="int",
        )
    )


def _confirm_local_index_rotation(confirm: bool, yes: bool) -> None:
    require_confirmation(confirm, yes, command_label="transcript index key rotate")
    if confirm or yes:
        return
    if not typer.confirm("Proceed with transcript index key rotation?"):
        raise CliError(DomainCode.VALIDATION_ERROR, "Operation cancelled by user.")


def _collect_transcript_index_records(
    client: WebexApiClient,
    *,
    from_utc: str,
    to_utc: str,
    max_pages: int = DEFAULT_SEARCH_MAX_PAGES,
) -> tuple[list[dict[str, Any]], list[str]]:
    meetings, _, warnings = collect_pages(
        lambda token: client.list_meetings(
            from_utc=from_utc,
            to_utc=to_utc,
            page_size=SEARCH_PAGE_SIZE,
            page_token=token,
        ),
        start_token=None,
        max_pages=max_pages,
    )
    records: list[dict[str, Any]] = []
    for meeting in meetings:
        current_meeting_id = str(meeting.get("id") or meeting.get("meetingId") or "")
        if not current_meeting_id:
            continue
        try:
            transcript_id, segments = _load_transcript_segments(client, current_meeting_id)
        except CliError as exc:
            if exc.code == DomainCode.NOT_FOUND:
                continue
            raise
        records.append(
            {
                "transcript_id": transcript_id,
                "meeting_id": current_meeting_id,
                "title": str(meeting.get("title") or meeting.get("topic") or current_meeting_id),
                "started_at": meeting.get("start") or meeting.get("startedAt") or meeting.get("started_at"),
                "segments": segments,
            }
        )
    return records, warnings


def _search_local_index(
    *,
    query: str,
    meeting_id: str | None,
    speaker: str | None,
    from_utc: str,
    to_utc: str,
    filter_value: str | None,
    sort_value: str,
    limit: int,
    case_sensitive: bool,
) -> list[dict[str, Any]]:
    rows = _local_index().search_rows(from_utc=from_utc, to_utc=to_utc, meeting_id=meeting_id)
    by_transcript: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = by_transcript.setdefault(
            row["transcript_id"],
            {
                "transcript_id": row["transcript_id"],
                "meeting_id": row["meeting_id"],
                "title": row["title"],
                "started_at": row.get("started_at"),
                "segments": [],
            },
        )
        bucket["segments"].append(
            {
                "segment_id": row["segment_id"],
                "speaker": row["speaker"] or UNKNOWN_SPEAKER,
                "start_offset_ms": row["start_offset_ms"],
                "end_offset_ms": row["end_offset_ms"],
                "text": row["text"],
            }
        )

    matches: list[dict[str, Any]] = []
    for bucket in by_transcript.values():
        filtered_segments = [
            segment
            for segment in bucket["segments"]
            if _speaker_matches(str(segment.get("speaker") or UNKNOWN_SPEAKER), speaker, case_sensitive=case_sensitive)
        ]
        matched, score, snippet = match_query(
            query,
            [segment.get("text") for segment in filtered_segments],
            case_sensitive=case_sensitive,
        )
        if not matched:
            continue
        normalized = {
            "transcript_id": bucket["transcript_id"],
            "meeting_id": bucket["meeting_id"],
            "title": bucket["title"],
            "started_at": bucket.get("started_at"),
            "segment_count": len(filtered_segments),
            "speaker_count": len({str(segment.get("speaker") or UNKNOWN_SPEAKER) for segment in filtered_segments}),
            "score": score,
            "snippet": snippet,
        }
        if not evaluate_filter(filter_value, normalized, TRANSCRIPT_SEARCH_SCHEMA, case_sensitive=case_sensitive):
            continue
        matches.append(normalized)
    return sort_items(matches, sort_value, TRANSCRIPT_SEARCH_SCHEMA, tie_breaker_field="transcript_id")[:limit]


def _process_batch_item(
    meeting: dict[str, Any],
    *,
    client: WebexApiClient,
    api_format: str,
    output_format: str,
    target_dir: Path,
    verify_checksum: bool,
    overwrite: bool,
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
        throttle.wait()
        status_value, _, _ = _read_transcript_status(client, meeting_id)
        if status_value != TranscriptStatus.READY:
            if status_value == TranscriptStatus.FAILED:
                failed_state = CliError(
                    DomainCode.INTERNAL_ERROR,
                    "Transcript processing failed.",
                    details={"meeting_id": meeting_id},
                )
                return (
                    {
                        "meeting_id": meeting_id,
                        "status": "failed",
                        "output_path": None,
                        "error_code": failed_state.code.value,
                        "error_message": failed_state.message,
                    },
                    None,
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

        transcript = _resolve_transcript_record(client, meeting_id)
        transcript_id = str(transcript["id"])
        checksum_meta: tuple[str, str] | None = None
        if verify_checksum:
            checksum_meta = checksum_from_metadata(transcript)
        filename = _batch_filename(meeting, output_format, artifact_id=transcript_id, download_url=None)
        out_path = target_dir / filename
        client.download_transcript_to_file(
            transcript_id,
            api_format,
            out_path,
            overwrite=overwrite,
            checksum=checksum_meta,
        )
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


@transcript_app.command("search", help="Search transcript content across meetings.")
def search_transcripts(
    query: str = typer.Option(..., "--query", help="Search text."),
    meeting_id: str | None = typer.Option(None, "--meeting-id", help="Limit search to a single meeting."),
    speaker: str | None = typer.Option(None, "--speaker", help="Limit search to transcript segments spoken by this speaker."),
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
    command = "transcript search"
    try:
        with profile_scope(None):
            meeting_id = meeting_id if isinstance(meeting_id, str) else None
            speaker = speaker if isinstance(speaker, str) else None
            filter_value = filter_value if isinstance(filter_value, str) else None
            sort_value = sort_value if isinstance(sort_value, str) else None
            page_token = page_token if isinstance(page_token, str) else None
            limit = limit if isinstance(limit, int) and not isinstance(limit, bool) else DEFAULT_SEARCH_LIMIT
            max_pages = max_pages if isinstance(max_pages, int) and not isinstance(max_pages, bool) else DEFAULT_SEARCH_MAX_PAGES
            case_sensitive = case_sensitive if isinstance(case_sensitive, bool) else False
            json_output = json_output if isinstance(json_output, bool) else False
            if not query.strip():
                raise CliError(DomainCode.VALIDATION_ERROR, "`--query` must not be empty.")
            if meeting_id is not None:
                meeting_id = validate_id(meeting_id, "meeting_id")
            if limit < 1:
                raise CliError(DomainCode.VALIDATION_ERROR, "`--limit` must be a positive integer.", details={"limit": limit})

            sort_field = primary_sort_field(sort_value, default_field="score")
            effective_sort = sort_value if sort_value and sort_value.strip() else "score:desc,started_at:desc"
            from_utc, to_utc = _resolve_search_window(from_value, to_value, tz)
            warnings: list[str] = []
            next_page_token: str | None = None
            matches: list[dict[str, Any]]
            try:
                with managed_client(client_factory=build_client) as client:
                    local_index = _local_index()
                    if _local_index_enabled() and local_index.exists() and local_index.is_stale(_local_index_stale_hours()):
                        records, refresh_warnings = _collect_transcript_index_records(client, from_utc=from_utc, to_utc=to_utc, max_pages=max_pages)
                        local_index.replace_all(records, from_utc=from_utc, to_utc=to_utc)
                        warnings.append("LOCAL_INDEX_REFRESHED")
                        warnings.extend(refresh_warnings)

                    meetings, next_page_token, upstream_warnings = collect_pages(
                        lambda token: client.list_meetings(
                            from_utc=from_utc,
                            to_utc=to_utc,
                            page_size=SEARCH_PAGE_SIZE,
                            page_token=token,
                        ),
                        start_token=page_token,
                        max_pages=max_pages,
                    )
                    warnings.extend(upstream_warnings)

                    matches = []
                    for meeting in meetings:
                        current_meeting_id = str(meeting.get("id") or meeting.get("meetingId") or "")
                        if not current_meeting_id:
                            continue
                        if meeting_id is not None and current_meeting_id != meeting_id:
                            continue

                        try:
                            transcript_id, segments = _load_transcript_segments(client, current_meeting_id)
                        except CliError as exc:
                            if exc.code == DomainCode.NOT_FOUND:
                                continue
                            raise

                        filtered_segments = [
                            segment
                            for segment in segments
                            if _speaker_matches(str(segment.get("speaker") or UNKNOWN_SPEAKER), speaker, case_sensitive=case_sensitive)
                        ]
                        matched, score, snippet = match_query(
                            query,
                            [segment.get("text") for segment in filtered_segments],
                            case_sensitive=case_sensitive,
                        )
                        if not matched:
                            continue

                        normalized = {
                            "transcript_id": transcript_id,
                            "meeting_id": current_meeting_id,
                            "title": str(meeting.get("title") or meeting.get("topic") or current_meeting_id),
                            "started_at": meeting.get("start") or meeting.get("startedAt") or meeting.get("started_at"),
                            "segment_count": len(filtered_segments),
                            "speaker_count": len({str(segment.get("speaker") or UNKNOWN_SPEAKER) for segment in filtered_segments}),
                            "score": score,
                            "snippet": snippet,
                        }
                        if not evaluate_filter(filter_value, normalized, TRANSCRIPT_SEARCH_SCHEMA, case_sensitive=case_sensitive):
                            continue
                        matches.append(normalized)
            except CliError as exc:
                if exc.code not in {DomainCode.NO_ACCESS, DomainCode.CAPABILITY_ERROR, DomainCode.TRANSCRIPT_DISABLED}:
                    raise
                local_index = _local_index()
                if not local_index.exists():
                    raise capability_unavailable(
                        "SEARCH_CAPABILITY_UNAVAILABLE",
                        "Transcript search is unavailable upstream and no local index is ready.",
                        details={"fallback_command": "webex transcript index rebuild"},
                    ) from exc
                matches = _search_local_index(
                    query=query,
                    meeting_id=meeting_id,
                    speaker=speaker,
                    from_utc=from_utc,
                    to_utc=to_utc,
                    filter_value=filter_value,
                    sort_value=effective_sort,
                    limit=limit,
                    case_sensitive=case_sensitive,
                )
                warnings = ["LOCAL_INDEX_FALLBACK"]

            sorted_matches = sort_items(matches, effective_sort, TRANSCRIPT_SEARCH_SCHEMA, tie_breaker_field="transcript_id")
            emit_success(
                command,
                {
                    "items": [_transcript_search_result(item, sort_field=sort_field) for item in sorted_matches[:limit]],
                    "next_page_token": next_page_token,
                },
                as_json=json_output,
                warnings=warnings,
            )
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


transcript_app.add_typer(index_app, name="index")
index_app.add_typer(index_key_app, name="key")


@transcript_app.command("segments", help="List normalized transcript segments for a meeting.")
def segments(
    meeting_id: str,
    speaker: str | None = typer.Option(None, "--speaker", help="Limit results to a specific speaker."),
    contains: str | None = typer.Option(None, "--contains", help="Limit results to segments containing text."),
    from_offset: float | None = typer.Option(None, "--from-offset", help="Minimum segment offset in seconds."),
    to_offset: float | None = typer.Option(None, "--to-offset", help="Maximum segment offset in seconds."),
    case_sensitive: bool = typer.Option(False, "--case-sensitive", help="Use case-sensitive speaker and text matching."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript segments"
    try:
        with profile_scope(None):
            speaker = speaker if isinstance(speaker, str) else None
            contains = contains if isinstance(contains, str) else None
            from_offset = from_offset if isinstance(from_offset, (int, float)) and not isinstance(from_offset, bool) else None
            to_offset = to_offset if isinstance(to_offset, (int, float)) and not isinstance(to_offset, bool) else None
            case_sensitive = case_sensitive if isinstance(case_sensitive, bool) else False
            json_output = json_output if isinstance(json_output, bool) else False
            meeting_id = validate_id(meeting_id, "meeting_id")
            if from_offset is not None and from_offset < 0:
                raise CliError(DomainCode.VALIDATION_ERROR, "`--from-offset` must be non-negative.", details={"from_offset": from_offset})
            if to_offset is not None and to_offset < 0:
                raise CliError(DomainCode.VALIDATION_ERROR, "`--to-offset` must be non-negative.", details={"to_offset": to_offset})
            if from_offset is not None and to_offset is not None and to_offset < from_offset:
                raise CliError(
                    DomainCode.VALIDATION_ERROR,
                    "`--to-offset` must be greater than or equal to `--from-offset`.",
                    details={"from_offset": from_offset, "to_offset": to_offset},
                )

            with managed_client(client_factory=build_client) as client:
                _, all_segments = _load_required_transcript_segments(client, meeting_id)

            from_offset_ms = int(from_offset * 1000) if from_offset is not None else None
            to_offset_ms = int(to_offset * 1000) if to_offset is not None else None
            items = [
                segment
                for segment in all_segments
                if _speaker_matches(str(segment.get("speaker") or UNKNOWN_SPEAKER), speaker, case_sensitive=case_sensitive)
                and _segment_overlaps_window(segment, from_offset_ms=from_offset_ms, to_offset_ms=to_offset_ms)
                and match_query(contains, [segment.get("text")], case_sensitive=case_sensitive)[0]
            ]
            emit_success(command, {"meeting_id": meeting_id, "items": items}, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@transcript_app.command("speakers", help="Summarize speakers present in a meeting transcript.")
def speakers(
    meeting_id: str,
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript speakers"
    try:
        with profile_scope(None):
            json_output = json_output if isinstance(json_output, bool) else False
            meeting_id = validate_id(meeting_id, "meeting_id")
            with managed_client(client_factory=build_client) as client:
                _, all_segments = _load_required_transcript_segments(client, meeting_id)

            aggregates: dict[str, dict[str, int | str]] = {}
            for segment in all_segments:
                speaker_name = str(segment.get("speaker") or UNKNOWN_SPEAKER)
                bucket = aggregates.setdefault(
                    speaker_name,
                    {"speaker": speaker_name, "segment_count": 0, "total_duration_ms": 0},
                )
                bucket["segment_count"] = int(bucket["segment_count"]) + 1
                start_offset_ms = segment.get("start_offset_ms")
                end_offset_ms = segment.get("end_offset_ms")
                if isinstance(start_offset_ms, int) and isinstance(end_offset_ms, int) and end_offset_ms >= start_offset_ms:
                    bucket["total_duration_ms"] = int(bucket["total_duration_ms"]) + (end_offset_ms - start_offset_ms)

            items = sorted(aggregates.values(), key=lambda item: str(item["speaker"]).lower())
            emit_success(command, {"meeting_id": meeting_id, "items": items}, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@index_app.command("rebuild", help="Rebuild the local transcript search index.")
def rebuild_index(
    from_value: str | None = typer.Option(None, "--from", help="Start date (YYYY-MM-DD or ISO 8601). Defaults to 30 days ago."),
    to_value: str | None = typer.Option(None, "--to", help="End date (YYYY-MM-DD or ISO 8601). Defaults to now."),
    tz: str | None = typer.Option(None, "--tz", help="Timezone for interpreting bare dates (e.g. America/New_York)."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript index rebuild"
    try:
        with profile_scope(None):
            from_utc, to_utc = _resolve_search_window(from_value, to_value, tz)
            with managed_client(client_factory=build_client) as client:
                records, warnings = _collect_transcript_index_records(client, from_utc=from_utc, to_utc=to_utc, max_pages=DEFAULT_SEARCH_MAX_PAGES)
            payload = _local_index().replace_all(records, from_utc=from_utc, to_utc=to_utc)
            emit_success(command, payload, as_json=json_output, warnings=warnings)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@index_key_app.command("rotate", help="Rotate the local transcript index encryption key.")
def rotate_index_key(
    confirm: bool = typer.Option(False, "--confirm", help="Confirm the rotation without prompting."),
    yes: bool = typer.Option(False, "--yes", help="Alias for --confirm."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript index key rotate"
    try:
        with profile_scope(None):
            _confirm_local_index_rotation(confirm, yes)
            payload = _local_index().rotate_key()
            emit_success(command, payload, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@transcript_app.command("status", help="Check whether a transcript is available for a meeting.")
def status(
    meeting_id: str,
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript status"
    try:
        with profile_scope(None):
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
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript get"
    try:
        with profile_scope(None):
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
        with profile_scope(None):
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
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript download"
    try:
        with profile_scope(None):
            meeting_id = validate_id(meeting_id, "meeting_id")
            api_format, output_format = _normalize_download_format(format_value)
            output_path = Path(out)
            with managed_client(client_factory=build_client) as client:
                transcript = _resolve_transcript_record(client, meeting_id)
                transcript_id = str(transcript["id"])
                warnings: list[str] = []
                checksum_meta: tuple[str, str] | None = None
                if verify_checksum:
                    checksum_meta = checksum_from_metadata(transcript)
                    if checksum_meta is None:
                        warnings.append("CHECKSUM_METADATA_MISSING")
                client.download_transcript_to_file(
                    transcript_id,
                    api_format,
                    output_path,
                    overwrite=overwrite,
                    checksum=checksum_meta,
                )
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
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing transcript files."),
    concurrency: int = typer.Option(
        DEFAULT_BATCH_CONCURRENCY,
        "--concurrency",
        help=f"Batch worker concurrency ({MIN_BATCH_CONCURRENCY}-{MAX_BATCH_CONCURRENCY}).",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "transcript batch"
    try:
        with profile_scope(None):
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
                terminal_errors_by_index: dict[int, CliError] = {}
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
                            client=client,
                            api_format=api_format,
                            output_format=output_format,
                            target_dir=target_dir,
                            verify_checksum=verify_checksum,
                            overwrite=overwrite,
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
                            if terminal_error is not None:
                                terminal_errors_by_index[idx] = terminal_error

                        while (
                            continue_mode or not terminal_errors_by_index
                        ) and next_to_submit < total and len(inflight) < concurrency:
                            idx, meeting = indexed_meetings[next_to_submit]
                            _submit(idx, meeting)
                            next_to_submit += 1

                if not continue_mode and terminal_errors_by_index and next_to_submit < total:
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
                if not continue_mode and terminal_errors_by_index:
                    first_index = min(terminal_errors_by_index)
                    raise typer.Exit(code=terminal_errors_by_index[first_index].exit_code)
    except typer.Exit:
        raise
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)
