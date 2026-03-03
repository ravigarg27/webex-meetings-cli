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


def test_recording_status_ambiguous_exits_2(monkeypatch) -> None:
    monkeypatch.setattr(recording_commands, "build_client", lambda: _AmbiguousRecordingClient())
    with pytest.raises(typer.Exit) as exc:
        recording_commands.status_recording(meeting_id="m1", recording_id=None, json_output=True)
    assert exc.value.exit_code == 2


def test_recording_download_quality_fallback_warning(monkeypatch, capsys) -> None:
    monkeypatch.setattr(recording_commands, "build_client", lambda: _DownloadRecordingClient())
    tmp_dir = Path(".test_tmp") / f"recording-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / "out.mp4"
    try:
        recording_commands.download_recording(
            meeting_id="m1",
            out=str(target),
            recording_id=None,
            quality="best",
            overwrite=False,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["warnings"] == ["QUALITY_FALLBACK"]
        assert payload["data"]["quality"] == "medium"
        assert target.exists()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
