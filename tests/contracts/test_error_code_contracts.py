import json
from pathlib import Path

import pytest
import typer

from webex_cli.commands import event as event_commands
from webex_cli.commands import meeting as meeting_commands
from webex_cli.commands import transcript as transcript_commands
from webex_cli.runtime import use_non_interactive


class _TemplateUnavailableClient:
    def probe_templates_access(self):
        return False


class _SegmentsUnavailableClient:
    def list_transcripts(self, meeting_id):
        return [{"id": "t1", "status": "ready"}]

    def download_transcript(self, transcript_id, format_value):
        return b'{"items":[]}'


def _fixture() -> dict:
    path = Path(__file__).resolve().parent / "fixtures" / "error_codes_v1_3.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_error_code_fixture_matches_runtime(monkeypatch, capsys) -> None:
    fixture = _fixture()

    monkeypatch.setattr(event_commands, "_run_ingress_server", lambda **kwargs: {"accepted": True, **kwargs})
    monkeypatch.setattr(event_commands, "build_client", lambda token=None: object())
    monkeypatch.setenv("WEBEX_WEBHOOK_SECRET", "super-secret")
    with pytest.raises(typer.Exit):
        event_commands.run_ingress(
            bind_host="127.0.0.1",
            bind_port=8787,
            public_base_url="https://example.test",
            path="/webhooks/webex",
            secret_env="WEBEX_WEBHOOK_SECRET",
            register=True,
            json_output=True,
        )
    ingress_payload = json.loads(capsys.readouterr().out)
    assert ingress_payload["error"]["code"] == fixture["event_ingress_capability_unavailable"]

    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: _TemplateUnavailableClient())
    with pytest.raises(typer.Exit):
        meeting_commands.list_templates(json_output=True)
    template_payload = json.loads(capsys.readouterr().out)
    assert template_payload["error"]["code"] == fixture["template_capability_unavailable"]

    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _SegmentsUnavailableClient())
    with pytest.raises(typer.Exit):
        transcript_commands.segments(meeting_id="m1", json_output=True)
    segments_payload = json.loads(capsys.readouterr().out)
    assert segments_payload["error"]["code"] == fixture["transcript_segments_unavailable"]

    with use_non_interactive(True):
        with pytest.raises(typer.Exit):
            event_commands.reset_checkpoint(checkpoint="cp1", confirm=False, json_output=True)
    confirm_payload = json.loads(capsys.readouterr().out)
    assert confirm_payload["error"]["code"] == fixture["confirmation_required_non_interactive"]
