import json
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

    def list_meetings(self, *, from_utc, to_utc, page_size, page_token, host_email=None):
        return ([{"id": "m1", "title": "Meeting", "start": "2026-01-01T01:00:00Z"}], None)

    def get_meeting(self, meeting_id):
        return {"id": meeting_id, "joinWebUrl": "https://example.test/join", "hasTranscription": True}

    def get_meeting_join_url(self, meeting_id):
        return {"joinWebUrl": "https://example.test/join"}

    def list_transcripts(self, meeting_id):
        return [{"id": "t1", "status": "ready", "updatedAt": "2026-01-01T02:00:00Z"}]

    def download_transcript(self, transcript_id, format_value):
        if format_value == "json":
            return b'{"text": "hello"}'
        return b"hello world"

    def list_recordings(self, **kwargs):
        return ([{"id": "r1", "meetingId": "m1", "createTime": "2026-01-01T03:00:00Z"}], None)

    def list_recordings_for_meeting(self, meeting_id):
        return [{"id": "r1", "meetingId": meeting_id}]

    def get_recording(self, recording_id):
        return {"id": recording_id, "status": "ready", "downloadUrl": "https://example.test/r1.mp4"}

    def download_recording(self, recording_id, quality):
        return (b"file-bytes", quality)


class _FakeStore:
    def __init__(self):
        self.record = None

    def save(self, record):
        self.record = record
        return "keyring"

    def clear(self):
        self.record = None
        return None

    def load(self):
        return self.record


def _mock_default_mode(monkeypatch):
    fake_store = _FakeStore()
    monkeypatch.setattr(auth_commands, "resolve_profile", lambda: "default")
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda *args, **kwargs: fake_store)
    monkeypatch.setattr(auth_commands, "load_credential_record", lambda: fake_store.record)
    monkeypatch.setattr(meeting_commands, "resolve_effective_timezone", lambda cli_tz: cli_tz or "UTC")
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _FakeClient())


def test_cli_smoke_mocked_mode(monkeypatch) -> None:
    _mock_default_mode(monkeypatch)
    monkeypatch.setenv("WEBEX_TOKEN", "token123")
    runner = CliRunner()

    assert runner.invoke(app, ["auth", "login"]).exit_code == 0
    assert runner.invoke(app, ["auth", "whoami", "--json"]).exit_code == 0
    meeting_result = runner.invoke(app, ["meeting", "list", "--from", "2026-01-01", "--to", "2026-01-02", "--json"])
    assert meeting_result.exit_code == 0, meeting_result.stdout
    last_result = runner.invoke(app, ["meeting", "list", "--last", "3", "--json"])
    assert last_result.exit_code == 0
    last_data = json.loads(last_result.stdout)
    assert len(last_data["data"]["items"]) <= 3
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
        lookback_days = int(os.environ.get("WEBEX_TEST_LAST_DAYS", "30"))
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
        os.environ["WEBEX_TOKEN"] = token

        login = runner.invoke(app, ["auth", "login", "--json"])
        assert login.exit_code == 0, login.stdout
        whoami = runner.invoke(app, ["auth", "whoami", "--json"])
        assert whoami.exit_code == 0, whoami.stdout
        meeting_list = runner.invoke(
            app,
            ["meeting", "list", "--from", date_from, "--to", date_to, "--json"],
        )
        assert meeting_list.exit_code == 0, meeting_list.stdout
        last_list = runner.invoke(app, ["meeting", "list", "--last", "5", "--json"])
        assert last_list.exit_code == 0, last_list.stdout
        last_data = json.loads(last_list.stdout)
        assert len(last_data["data"]["items"]) <= 5

        # Parse meeting list to drive downstream tests data-driven.
        meeting_items = json.loads(meeting_list.stdout)["data"]["items"]

        def _find_meeting_with(items, field):
            return next((m["meeting_id"] for m in items if m.get(field)), None)

        first_meeting_id = meeting_items[0]["meeting_id"] if meeting_items else None
        meeting_id_with_recording = _find_meeting_with(meeting_items, "has_recording")
        meeting_id_with_transcript = _find_meeting_with(meeting_items, "has_transcript")

        # meeting get
        if first_meeting_id:
            meeting_get = runner.invoke(app, ["meeting", "get", first_meeting_id, "--json"])
            assert meeting_get.exit_code == 0, meeting_get.stdout
        else:
            print("[skip] meeting get: no meetings in date range")

        # meeting join-url
        if first_meeting_id:
            join_url = runner.invoke(app, ["meeting", "join-url", first_meeting_id, "--json"])
            assert join_url.exit_code == 0, join_url.stdout
        else:
            print("[skip] meeting join-url: no meetings in date range")

        # recording list (independent, same date range)
        rec_list = runner.invoke(
            app,
            ["recording", "list", "--from", date_from, "--to", date_to, "--json"],
        )
        assert rec_list.exit_code == 0, rec_list.stdout

        # recording status
        if meeting_id_with_recording:
            rec_status = runner.invoke(app, ["recording", "status", meeting_id_with_recording, "--json"])
            assert rec_status.exit_code == 0, rec_status.stdout
        else:
            print("[skip] recording status: no meeting with has_recording=true in date range")

        # recording download
        if meeting_id_with_recording:
            rec_out = tmp_dir / "recording.mp4"
            rec_dl = runner.invoke(
                app,
                ["recording", "download", meeting_id_with_recording, "--out", str(rec_out), "--json"],
            )
            assert rec_dl.exit_code == 0, rec_dl.stdout
            assert rec_out.exists() and rec_out.stat().st_size > 0, "recording download produced empty file"
        else:
            print("[skip] recording download: no meeting with has_recording=true in date range")

        # transcript status
        if meeting_id_with_transcript:
            tx_status = runner.invoke(app, ["transcript", "status", meeting_id_with_transcript, "--json"])
            assert tx_status.exit_code == 0, tx_status.stdout
        else:
            print("[skip] transcript status: no meeting with has_transcript=true in date range")

        # transcript get
        if meeting_id_with_transcript:
            tx_get = runner.invoke(
                app,
                ["transcript", "get", meeting_id_with_transcript, "--format", "text", "--json"],
            )
            assert tx_get.exit_code == 0, tx_get.stdout
        else:
            print("[skip] transcript get: no meeting with has_transcript=true in date range")

        # transcript download
        if meeting_id_with_transcript:
            tx_out = tmp_dir / "transcript.txt"
            tx_dl = runner.invoke(
                app,
                ["transcript", "download", meeting_id_with_transcript, "--format", "txt", "--out", str(tx_out), "--json"],
            )
            assert tx_dl.exit_code == 0, tx_dl.stdout
            assert tx_out.exists() and tx_out.stat().st_size > 0, "transcript download produced empty file"
        else:
            print("[skip] transcript download: no meeting with has_transcript=true in date range")

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
        os.environ.pop("WEBEX_TOKEN", None)
        shutil.rmtree(tmp_dir, ignore_errors=True)
