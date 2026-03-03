import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from webex_cli.cli import app
from webex_cli.commands import auth as auth_commands
from webex_cli.commands import meeting as meeting_commands
from webex_cli.commands import recording as recording_commands
from webex_cli.commands import transcript as transcript_commands


class _FakeClient:
    def whoami(self):
        return {
            "user_id": "u1",
            "display_name": "User One",
            "primary_email": "u1@example.test",
            "org_id": "org1",
            "site_url": "https://site.example.test",
            "token_state": "valid",
        }

    def probe_meetings_access(self):
        return None

    def list_meetings(self, **kwargs):
        return ([{"id": "m1", "title": "Meeting", "start": "2026-01-01T01:00:00Z"}], None)

    def get_meeting(self, meeting_id):
        return {"id": meeting_id, "joinWebUrl": "https://example.test/join", "hasTranscript": True}

    def get_meeting_join_url(self, meeting_id):
        return {"joinWebUrl": "https://example.test/join"}

    def get_transcript_status(self, meeting_id):
        return {"status": "ready", "updatedAt": "2026-01-01T02:00:00Z"}

    def get_transcript(self, meeting_id, format_value):
        if format_value == "json":
            return {"id": "t1", "content": {"text": "hello"}}
        return {"id": "t1", "content": "hello world"}

    def list_recordings(self, **kwargs):
        return ([{"id": "r1", "meetingId": "m1", "createTime": "2026-01-01T03:00:00Z"}], None)

    def list_recordings_for_meeting(self, meeting_id):
        return [{"id": "r1", "meetingId": meeting_id}]

    def get_recording(self, recording_id):
        return {"id": recording_id, "status": "ready", "downloadUrl": "https://example.test/r1.mp4"}

    def download_recording(self, recording_id, quality):
        return (b"file-bytes", quality)


class _FakeStore:
    record = None

    def save(self, record):
        _FakeStore.record = record
        return "keyring"

    def clear(self):
        _FakeStore.record = None
        return None

    def load(self):
        return _FakeStore.record


def _mock_default_mode(monkeypatch):
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda: _FakeStore())
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _FakeClient())


def test_cli_smoke_mocked_mode(monkeypatch) -> None:
    _mock_default_mode(monkeypatch)
    runner = CliRunner()

    assert runner.invoke(app, ["auth", "login", "--token", "token123"]).exit_code == 0
    assert runner.invoke(app, ["auth", "whoami", "--json"]).exit_code == 0
    assert runner.invoke(app, ["meeting", "list", "--from", "2026-01-01", "--to", "2026-01-02", "--json"]).exit_code == 0
    assert runner.invoke(app, ["transcript", "get", "m1", "--format", "text", "--json"]).exit_code == 0
    tmp_dir = Path(".test_tmp") / f"e2e-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_file = tmp_dir / "r1.mp4"
    try:
        assert (
            runner.invoke(
                app,
                ["recording", "download", "m1", "--out", str(out_file), "--quality", "best", "--json"],
            ).exit_code
            == 0
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.mark.skipif(
    os.environ.get("WEBEX_E2E_LIVE") != "1"
    or not os.environ.get("WEBEX_TEST_TOKEN"),
    reason="Live e2e requires WEBEX_E2E_LIVE=1 and WEBEX_TEST_TOKEN",
)
def test_cli_smoke_live_mode() -> None:
    runner = CliRunner()
    token = os.environ["WEBEX_TEST_TOKEN"]
    if os.environ.get("WEBEX_TEST_FROM") and os.environ.get("WEBEX_TEST_TO"):
        date_from = os.environ["WEBEX_TEST_FROM"]
        date_to = os.environ["WEBEX_TEST_TO"]
    else:
        lookback_days = int(os.environ.get("WEBEX_TEST_LAST_DAYS", "5"))
        today = datetime.now(timezone.utc).date()
        date_to = today.isoformat()
        date_from = (today - timedelta(days=lookback_days)).isoformat()

    tmp_dir = Path(".test_tmp") / f"e2e-live-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    old_appdata = os.environ.get("APPDATA")
    old_xdg = os.environ.get("XDG_CONFIG_HOME")
    try:
        # Isolate credential writes from developer machine state.
        os.environ["APPDATA"] = str(tmp_dir)
        os.environ["XDG_CONFIG_HOME"] = str(tmp_dir)

        login = runner.invoke(app, ["auth", "login", "--token", token, "--json"])
        assert login.exit_code == 0, login.stdout
        whoami = runner.invoke(app, ["auth", "whoami", "--json"])
        assert whoami.exit_code == 0, whoami.stdout
        meeting_list = runner.invoke(
            app,
            ["meeting", "list", "--from", date_from, "--to", date_to, "--json"],
        )
        assert meeting_list.exit_code == 0, meeting_list.stdout
        logout = runner.invoke(app, ["auth", "logout", "--json"])
        assert logout.exit_code == 0, logout.stdout
    finally:
        if old_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = old_appdata
        if old_xdg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = old_xdg
        shutil.rmtree(tmp_dir, ignore_errors=True)
