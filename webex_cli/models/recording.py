from __future__ import annotations

from enum import Enum


class RecordingStatus(str, Enum):
    NOT_RECORDED = "not_recorded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    NO_ACCESS = "no_access"
    NOT_FOUND = "not_found"
    RECORDING_DISABLED = "recording_disabled"


def map_recording_status(value: str | None) -> RecordingStatus:
    normalized = (value or "").strip().lower()
    mapping = {
        "processing": RecordingStatus.PROCESSING,
        "in_progress": RecordingStatus.PROCESSING,
        "ready": RecordingStatus.READY,
        "available": RecordingStatus.READY,
        "failed": RecordingStatus.FAILED,
        "error": RecordingStatus.FAILED,
        "no_access": RecordingStatus.NO_ACCESS,
        "forbidden": RecordingStatus.NO_ACCESS,
        "not_found": RecordingStatus.NOT_FOUND,
        "missing": RecordingStatus.NOT_FOUND,
        "not_recorded": RecordingStatus.NOT_RECORDED,
        "disabled": RecordingStatus.RECORDING_DISABLED,
        "recording_disabled": RecordingStatus.RECORDING_DISABLED,
    }
    return mapping.get(normalized, RecordingStatus.FAILED)

