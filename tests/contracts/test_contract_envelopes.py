import json
from pathlib import Path

from typer.testing import CliRunner

from webex_cli.cli import app
from webex_cli.commands import auth as auth_commands
from webex_cli.commands import meeting as meeting_commands
from webex_cli.commands import recording as recording_commands
from webex_cli.commands import transcript as transcript_commands
from webex_cli.config.credentials import CredentialRecord
from webex_cli.errors import DomainCode, exit_code_for


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

    def list_transcripts(self, meeting_id):
        return [{"id": "t1", "status": "ready"}]

    def list_recordings_for_meeting(self, meeting_id):
        return [{"id": "r1"}]


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


def _load_contract() -> dict:
    path = Path(__file__).resolve().parent / "fixtures" / "envelope_contract_v1_1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_envelope_shape(payload: dict, contract: dict) -> None:
    for key in contract["required_top_level_keys"]:
        assert key in payload
    for key in contract["required_meta_keys"]:
        assert key in payload["meta"]
    assert payload["meta"]["schema_version"] == contract["schema_version"]


def test_json_envelope_compatibility_for_command_groups(monkeypatch) -> None:
    fake_store = _FakeStore()
    contract = _load_contract()
    runner = CliRunner()

    monkeypatch.setenv("WEBEX_TOKEN", "token123")
    monkeypatch.setattr(auth_commands, "resolve_profile", lambda: "default")
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda *args, **kwargs: fake_store)
    monkeypatch.setattr(
        auth_commands,
        "load_credential_record",
        lambda: CredentialRecord(token="token123", backend="keyring", auth_type="pat"),
    )
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _FakeClient())

    commands = [
        ["auth", "login", "--json"],
        ["auth", "whoami", "--json"],
        ["auth", "logout", "--json"],
        ["profile", "list", "--json"],
        ["meeting", "list", "--from", "2026-01-01", "--to", "2026-01-02", "--json"],
        ["transcript", "status", "m1", "--json"],
        ["recording", "status", "m1", "--json"],
    ]
    for cmd in commands:
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        _assert_envelope_shape(payload, contract)


def test_error_envelope_compatibility(monkeypatch) -> None:
    contract = _load_contract()
    runner = CliRunner()
    result = runner.invoke(app, ["profile", "use", "missing-profile", "--json"])
    assert result.exit_code == exit_code_for(DomainCode.NOT_FOUND)
    payload = json.loads(result.stdout)
    _assert_envelope_shape(payload, contract)
    assert payload["ok"] is False
