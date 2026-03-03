import json

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


def test_transcript_status_maps_not_found(monkeypatch, capsys) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda: _TranscriptClientStatusNotFound())
    transcript_commands.status(meeting_id="m1", json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "not_found"


def test_transcript_wait_processing_to_ready(monkeypatch, capsys) -> None:
    client = _TranscriptClientWaitReady()
    monkeypatch.setattr(transcript_commands, "build_client", lambda: client)
    monkeypatch.setattr(transcript_commands.time, "sleep", lambda _: None)
    transcript_commands.wait_transcript(meeting_id="m1", timeout=10, interval=1, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "ready"
    assert client.calls == 2


def test_transcript_wait_no_access_exits_5(monkeypatch) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda: _TranscriptClientWaitNoAccess())
    with pytest.raises(typer.Exit) as exc:
        transcript_commands.wait_transcript(meeting_id="m1", timeout=10, interval=1, json_output=True)
    assert exc.value.exit_code == 5

