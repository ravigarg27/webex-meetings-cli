import json
import shutil
from pathlib import Path
import uuid

import pytest
import typer

from webex_cli.commands import transcript as transcript_commands
from webex_cli.errors import CliError, DomainCode


class _TranscriptClientStatusNotFound:
    def get_transcript_status(self, meeting_id):
        raise CliError(DomainCode.NOT_FOUND, "missing")


class _TranscriptClientWaitReady:
    def __init__(self) -> None:
        self.calls = 0

    def get_transcript_status(self, meeting_id):
        self.calls += 1
        if self.calls == 1:
            return {"status": "processing"}
        return {"status": "ready", "updatedAt": "2026-03-02T00:00:00Z"}


class _TranscriptClientWaitNoAccess:
    def get_transcript_status(self, meeting_id):
        raise CliError(DomainCode.NO_ACCESS, "forbidden")


class _TranscriptClientDisabled:
    def get_transcript_status(self, meeting_id):
        raise CliError(DomainCode.TRANSCRIPT_DISABLED, "disabled")


class _TranscriptFormatClient:
    def __init__(self) -> None:
        self.last_format = None

    def get_transcript(self, meeting_id, format_value):
        self.last_format = format_value
        return {"content": "ok"}


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
