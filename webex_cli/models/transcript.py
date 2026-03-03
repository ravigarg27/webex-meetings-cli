from __future__ import annotations

from enum import Enum


class TranscriptStatus(str, Enum):
    NOT_RECORDED = "not_recorded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    NO_ACCESS = "no_access"
    NOT_FOUND = "not_found"
    TRANSCRIPT_DISABLED = "transcript_disabled"


def map_transcript_status(value: str | None) -> TranscriptStatus:
    normalized = (value or "").strip().lower()
    mapping = {
        "processing": TranscriptStatus.PROCESSING,
        "in_progress": TranscriptStatus.PROCESSING,
        "ready": TranscriptStatus.READY,
        "available": TranscriptStatus.READY,
        "failed": TranscriptStatus.FAILED,
        "error": TranscriptStatus.FAILED,
        "no_access": TranscriptStatus.NO_ACCESS,
        "forbidden": TranscriptStatus.NO_ACCESS,
        "not_found": TranscriptStatus.NOT_FOUND,
        "missing": TranscriptStatus.NOT_FOUND,
        "not_recorded": TranscriptStatus.NOT_RECORDED,
        "disabled": TranscriptStatus.TRANSCRIPT_DISABLED,
        "transcript_disabled": TranscriptStatus.TRANSCRIPT_DISABLED,
    }
    return mapping.get(normalized, TranscriptStatus.FAILED)

