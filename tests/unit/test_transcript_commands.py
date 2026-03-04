import json
import shutil
import time
from pathlib import Path
import uuid

import pytest
import typer

from webex_cli.commands import transcript as transcript_commands
from webex_cli.errors import CliError, DomainCode


class _TranscriptClientStatusNotFound:
    def list_transcripts(self, meeting_id):
        return []


class _TranscriptClientWaitReady:
    def __init__(self) -> None:
        self.calls = 0

    def list_transcripts(self, meeting_id):
        self.calls += 1
        if self.calls == 1:
            return [{"id": "t1", "status": "processing"}]
        return [{"id": "t1", "status": "ready", "updatedAt": "2026-03-02T00:00:00Z"}]


class _TranscriptClientWaitNoAccess:
    def list_transcripts(self, meeting_id):
        raise CliError(DomainCode.NO_ACCESS, "forbidden")


class _TranscriptClientDisabled:
    def list_transcripts(self, meeting_id):
        raise CliError(DomainCode.TRANSCRIPT_DISABLED, "disabled")


class _TranscriptFormatClient:
    def __init__(self) -> None:
        self.last_format = None

    def list_transcripts(self, meeting_id):
        return [{"id": "t1"}]

    def download_transcript(self, transcript_id, format_value):
        self.last_format = format_value
        return b"ok"


class _TranscriptChecksumClient:
    def list_transcripts(self, meeting_id):
        return [{"id": "t1", "checksum_sha256": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"}]

    def download_transcript(self, transcript_id, format_value):
        return b"hello"


class _BatchFailFastClient:
    def __init__(self) -> None:
        self.downloaded: list[str] = []

    def list_meetings(self, *, from_utc, to_utc, page_size, page_token, host_email=None):  # noqa: ANN001
        return (
            [
                {"id": "m1", "start": "2026-01-01T00:00:00Z"},
                {"id": "m2", "start": "2026-01-01T00:00:00Z"},
                {"id": "m3", "start": "2026-01-01T00:00:00Z"},
                {"id": "m4", "start": "2026-01-01T00:00:00Z"},
            ],
            None,
        )

    def list_transcripts(self, meeting_id):
        if meeting_id == "m1":
            time.sleep(0.05)
            return [{"id": "t1", "status": "ready"}]
        if meeting_id == "m2":
            return [{"id": "t2", "status": "failed"}]
        return [{"id": f"t-{meeting_id}", "status": "ready"}]

    def download_transcript(self, transcript_id, format_value):
        self.downloaded.append(transcript_id)
        return b"batch-data"


class _BatchThrottleClient:
    def __init__(self) -> None:
        self.calls = 0

    def list_meetings(self, *, from_utc, to_utc, page_size, page_token, host_email=None):  # noqa: ANN001
        return ([{"id": "m1"}, {"id": "m2"}], None)

    def list_transcripts(self, meeting_id):
        self.calls += 1
        if self.calls == 1:
            raise CliError(DomainCode.RATE_LIMITED, "rate limited")
        return [{"id": f"t-{meeting_id}", "status": "ready"}]

    def download_transcript(self, transcript_id, format_value):
        return b"ok"


def test_transcript_status_maps_not_found(monkeypatch, capsys) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptClientStatusNotFound())
    transcript_commands.status(meeting_id="m1", json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "not_found"


def test_transcript_wait_processing_to_ready(monkeypatch, capsys) -> None:
    client = _TranscriptClientWaitReady()
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: client)
    monkeypatch.setattr(transcript_commands.time, "sleep", lambda _: None)
    transcript_commands.wait_transcript(meeting_id="m1", timeout=10, interval=1, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "ready"
    assert client.calls == 2


def test_transcript_wait_no_access_exits_5(monkeypatch) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptClientWaitNoAccess())
    with pytest.raises(typer.Exit) as exc:
        transcript_commands.wait_transcript(meeting_id="m1", timeout=10, interval=1, json_output=True)
    assert exc.value.exit_code == 5


def test_transcript_status_disabled_mapping(monkeypatch, capsys) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptClientDisabled())
    transcript_commands.status(meeting_id="m1", json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "transcript_disabled"


def test_transcript_get_accepts_txt_alias(monkeypatch, capsys) -> None:
    client = _TranscriptFormatClient()
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: client)
    transcript_commands.get_transcript(meeting_id="m1", format_value="txt", json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["format"] == "text"
    assert client.last_format == "text"


def test_transcript_download_accepts_text_alias(monkeypatch, capsys) -> None:
    client = _TranscriptFormatClient()
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: client)
    tmp_dir = Path(".test_tmp") / f"transcript-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path = tmp_dir / "out.txt"
    try:
        transcript_commands.download_transcript(
            meeting_id="m1",
            format_value="text",
            out=str(out_path),
            overwrite=False,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["data"]["format"] == "txt"
        assert client.last_format == "text"
        assert out_path.exists()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_transcript_download_txt_alias_uses_text_api_format(monkeypatch, capsys) -> None:
    client = _TranscriptFormatClient()
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: client)
    tmp_dir = Path(".test_tmp") / f"transcript-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path = tmp_dir / "out.txt"
    try:
        transcript_commands.download_transcript(
            meeting_id="m1",
            format_value="txt",
            out=str(out_path),
            overwrite=False,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["data"]["format"] == "txt"
        assert client.last_format == "text"
        assert out_path.exists()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_transcript_download_verify_checksum_success(monkeypatch, capsys) -> None:
    client = _TranscriptChecksumClient()
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: client)
    tmp_dir = Path(".test_tmp") / f"transcript-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path = tmp_dir / "out.txt"
    try:
        transcript_commands.download_transcript(
            meeting_id="m1",
            format_value="txt",
            out=str(out_path),
            verify_checksum=True,
            overwrite=False,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert out_path.exists()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_transcript_download_verify_checksum_mismatch(monkeypatch) -> None:
    class _MismatchClient(_TranscriptChecksumClient):
        def download_transcript(self, transcript_id, format_value):
            return b"not-hello"

    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _MismatchClient())
    tmp_dir = Path(".test_tmp") / f"transcript-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path = tmp_dir / "out.txt"
    try:
        with pytest.raises(typer.Exit) as exc:
            transcript_commands.download_transcript(
                meeting_id="m1",
                format_value="txt",
                out=str(out_path),
                verify_checksum=True,
                overwrite=False,
                json_output=True,
            )
        assert exc.value.exit_code == 10
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_transcript_batch_fail_fast_stops_queue_and_marks_aborted(monkeypatch, capsys) -> None:
    client = _BatchFailFastClient()
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: client)

    tmp_dir = Path(".test_tmp") / f"transcript-batch-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        with pytest.raises(typer.Exit) as exc:
            transcript_commands.batch_transcripts(
                from_value="2026-01-01",
                to_value="2026-01-02",
                download_dir=str(tmp_dir),
                tz="UTC",
                format_value="txt",
                continue_on_error=False,
                concurrency=2,
                json_output=True,
            )
        assert exc.value.exit_code == 10
        payload = json.loads(capsys.readouterr().out)
        results = {item["meeting_id"]: item for item in payload["data"]["results"]}
        assert results["m2"]["status"] == "failed"
        assert results["m3"]["error_code"] == "FAIL_FAST_ABORTED"
        assert results["m4"]["error_code"] == "FAIL_FAST_ABORTED"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_transcript_batch_rejects_invalid_concurrency(monkeypatch) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _BatchFailFastClient())
    with pytest.raises(typer.Exit) as exc:
        transcript_commands.batch_transcripts(
            from_value="2026-01-01",
            to_value="2026-01-02",
            download_dir=str(Path(".test_tmp") / f"transcript-batch-{uuid.uuid4().hex}"),
            tz="UTC",
            format_value="txt",
            continue_on_error=True,
            concurrency=0,
            json_output=True,
        )
    assert exc.value.exit_code == 2


def test_transcript_batch_applies_adaptive_throttle(monkeypatch, capsys) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _BatchThrottleClient())
    monkeypatch.setattr(transcript_commands.time, "sleep", lambda seconds: sleeps.append(seconds))

    tmp_dir = Path(".test_tmp") / f"transcript-batch-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        transcript_commands.batch_transcripts(
            from_value="2026-01-01",
            to_value="2026-01-02",
            download_dir=str(tmp_dir),
            tz="UTC",
            format_value="txt",
            continue_on_error=True,
            concurrency=1,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert "ADAPTIVE_THROTTLE_APPLIED" in payload["warnings"]
        assert any(delay > 0 for delay in sleeps)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
