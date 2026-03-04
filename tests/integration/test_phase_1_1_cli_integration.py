import json

from typer.testing import CliRunner

from webex_cli.cli import app
from webex_cli.commands import auth as auth_commands
from webex_cli.commands import common as common_commands
from webex_cli.config.credentials import CredentialRecord
from webex_cli.oauth import OAuthDeviceConfig


class _FakeAuthClient:
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


class _MemoryCredentialStore:
    records: dict[str, CredentialRecord] = {}

    def __init__(self, profile: str = "default") -> None:
        self.profile = profile

    def save(self, record: CredentialRecord) -> str:
        _MemoryCredentialStore.records[self.profile] = record
        return "keyring"

    def load(self) -> CredentialRecord:
        return _MemoryCredentialStore.records[self.profile]

    def clear(self) -> None:
        _MemoryCredentialStore.records.pop(self.profile, None)

    def mark_invalid(self, reason: str) -> None:  # pragma: no cover
        record = _MemoryCredentialStore.records[self.profile]
        record.invalid_reason = reason

    def clear_invalid(self) -> None:  # pragma: no cover
        record = _MemoryCredentialStore.records[self.profile]
        record.invalid_reason = None


def test_profile_auth_isolation_with_cli(monkeypatch) -> None:
    _MemoryCredentialStore.records = {}
    runner = CliRunner()

    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeAuthClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", _MemoryCredentialStore)
    monkeypatch.setattr(common_commands, "CredentialStore", _MemoryCredentialStore)
    monkeypatch.setenv("WEBEX_CREDENTIAL_FALLBACK_POLICY", "allow_file_fallback")

    assert runner.invoke(app, ["profile", "create", "work", "--json"]).exit_code == 0

    monkeypatch.setenv("WEBEX_TOKEN", "token-default")
    assert runner.invoke(app, ["auth", "login", "--json"]).exit_code == 0

    monkeypatch.setenv("WEBEX_TOKEN", "token-work")
    assert runner.invoke(app, ["--profile", "work", "auth", "login", "--json"]).exit_code == 0

    who_default = runner.invoke(app, ["auth", "whoami", "--json"])
    who_work = runner.invoke(app, ["--profile", "work", "auth", "whoami", "--json"])
    assert who_default.exit_code == 0
    assert who_work.exit_code == 0

    default_payload = json.loads(who_default.stdout)
    work_payload = json.loads(who_work.stdout)
    assert default_payload["data"]["profile"] == "default"
    assert work_payload["data"]["profile"] == "work"
    assert _MemoryCredentialStore.records["default"].token == "token-default"
    assert _MemoryCredentialStore.records["work"].token == "token-work"


def test_oauth_config_precedence_from_cli_flags(monkeypatch) -> None:
    runner = CliRunner()
    captured: dict[str, object] = {}

    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeAuthClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", _MemoryCredentialStore)
    monkeypatch.setattr(common_commands, "CredentialStore", _MemoryCredentialStore)

    def _capture_config(**kwargs):
        captured.update(kwargs)
        return OAuthDeviceConfig(
            client_id=str(kwargs.get("client_id") or "fallback-client"),
            device_authorize_url=str(kwargs.get("device_authorize_url") or "https://example.test/device/authorize"),
            token_url=str(kwargs.get("token_url") or "https://example.test/device/token"),
            scope=str(kwargs.get("scope") or "spark:all"),
            poll_interval_seconds=int(kwargs.get("poll_interval_seconds") or 5),
            timeout_seconds=int(kwargs.get("timeout_seconds") or 60),
        )

    monkeypatch.setattr(auth_commands, "resolve_oauth_device_config", _capture_config)
    monkeypatch.setattr(
        auth_commands,
        "start_device_authorization",
        lambda config: {
            "device_code": "d1",
            "user_code": "ABCD",
            "verification_uri": "https://example.test/device",
            "verification_uri_complete": "https://example.test/device?user_code=ABCD",
            "expires_in": 60,
            "interval_seconds": 2,
        },
    )
    monkeypatch.setattr(
        auth_commands,
        "poll_for_device_token",
        lambda config, *, device_code, interval_seconds: auth_commands.OAuthTokenBundle(
            access_token="oauth-token",
            refresh_token="refresh-token",
            expires_at="2026-04-01T00:00:00+00:00",
            scopes=["spark:all"],
        ),
    )
    monkeypatch.setenv("WEBEX_OAUTH_CLIENT_ID", "env-client-id")
    result = runner.invoke(
        app,
        [
            "auth",
            "login",
            "--oauth-device-flow",
            "--oauth-client-id",
            "flag-client-id",
            "--oauth-token-url",
            "https://flag.example.test/token",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert captured["client_id"] == "flag-client-id"
    assert captured["token_url"] == "https://flag.example.test/token"
