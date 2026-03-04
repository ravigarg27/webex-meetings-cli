import json
import shutil
import uuid
from pathlib import Path

import pytest
import typer

from webex_cli.commands import recording as recording_commands


class _AmbiguousRecordingClient:
    def list_recordings_for_meeting(self, meeting_id):
        return [{"id": "r1"}, {"id": "r2"}]


class _DownloadRecordingClient:
    def list_recordings_for_meeting(self, meeting_id):
        return [{"id": "r1"}]

    def download_recording(self, recording_id, quality):
        return (b"abc", "medium")


class _DownloadRecordingChecksumClient:
    def list_recordings_for_meeting(self, meeting_id):
        return [{"id": "r1", "checksum_md5": "900150983cd24fb0d6963f7d28e17f72"}]

    def download_recording(self, recording_id, quality):
        return (b"abc", "best")


class _RecordingStatusNoFieldClient:
    def list_recordings_for_meeting(self, meeting_id):
        return [{"id": "r1"}]


class _MismatchedRecordingClient:
    def get_recording(self, recording_id):
        return {"id": recording_id, "meetingId": "other-meeting"}


class _UnknownRecordingStatusClient:
    def list_recordings_for_meeting(self, meeting_id):
        return [{"id": "r1", "status": "future_status"}]


class _SinglePageRecordingClient:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def list_recordings(self, *, from_utc, to_utc, page_size, page_token, host_email=None, meeting_id=None):  # noqa: ANN001
        self.calls.append(page_token)
        return (
            [
                {
                    "id": "r9",
                    "meetingId": "m9",
                    "createTime": "2026-01-03T10:00:00Z",
                    "durationSeconds": 300,
                    "sizeBytes": 1024,
                }
            ],
            "next-recording-token",
        )


def test_recording_status_ambiguous_exits_2(monkeypatch) -> None:
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _AmbiguousRecordingClient())
    with pytest.raises(typer.Exit) as exc:
        recording_commands.status_recording(meeting_id="m1", recording_id=None, json_output=True)
    assert exc.value.exit_code == 2


def test_recording_download_quality_fallback_warning(monkeypatch, capsys) -> None:
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _DownloadRecordingClient())
    tmp_dir = Path(".test_tmp") / f"recording-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / "out.mp4"
    try:
        recording_commands.download_recording(
            meeting_id="m1",
            out=str(target),
            recording_id=None,
            quality="best",
            verify_checksum=False,
            overwrite=False,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["warnings"] == ["QUALITY_FALLBACK"]
        assert payload["data"]["quality"] == "medium"
        assert target.exists()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_recording_list_with_page_token_returns_single_page_and_next_token(monkeypatch, capsys) -> None:
    client = _SinglePageRecordingClient()
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: client)
    recording_commands.list_recordings(
        from_value="2026-01-01",
        to_value="2026-01-04",
        last=None,
        tz="UTC",
        page_size=10,
        page_token="resume-token",
        json_output=True,
    )
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["data"]["items"]) == 1
    assert payload["data"]["items"][0]["recording_id"] == "r9"
    assert payload["data"]["next_page_token"] == "next-recording-token"
    assert client.calls == ["resume-token"]


def test_recording_status_without_status_defaults_processing(monkeypatch, capsys) -> None:
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _RecordingStatusNoFieldClient())
    recording_commands.status_recording(meeting_id="m1", recording_id=None, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "processing"


def test_recording_status_rejects_meeting_recording_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _MismatchedRecordingClient())
    with pytest.raises(typer.Exit) as exc:
        recording_commands.status_recording(meeting_id="m1", recording_id="r1", json_output=True)
    assert exc.value.exit_code == 2


def test_recording_status_unknown_status_warns(monkeypatch, capsys) -> None:
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _UnknownRecordingStatusClient())
    recording_commands.status_recording(meeting_id="m1", recording_id=None, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "failed"
    assert payload["warnings"] == ["UNMAPPED_RECORDING_STATUS"]


def test_recording_download_verify_checksum_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _DownloadRecordingChecksumClient())
    tmp_dir = Path(".test_tmp") / f"recording-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / "out.mp4"
    try:
        recording_commands.download_recording(
            meeting_id="m1",
            out=str(target),
            recording_id=None,
            quality="best",
            verify_checksum=True,
            overwrite=False,
            profile=None,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_recording_download_verify_checksum_mismatch(monkeypatch) -> None:
    class _MismatchClient(_DownloadRecordingChecksumClient):
        def download_recording(self, recording_id, quality):
            return (b"zzz", "best")

    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _MismatchClient())
    tmp_dir = Path(".test_tmp") / f"recording-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / "out.mp4"
    try:
        with pytest.raises(typer.Exit) as exc:
            recording_commands.download_recording(
                meeting_id="m1",
                out=str(target),
                recording_id=None,
                quality="best",
                verify_checksum=True,
                overwrite=False,
                profile=None,
                json_output=True,
            )
        assert exc.value.exit_code == 10
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
