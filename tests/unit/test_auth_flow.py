import json

import pytest
import typer

from webex_cli.commands import auth as auth_commands
from webex_cli.oauth import OAuthDeviceConfig, OAuthTokenBundle


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


class _FakeStore:
    def __init__(self):
        self.saved = None
        self.cleared = False

    def save(self, record):
        self.saved = record
        return "file_fallback"

    def clear(self):
        self.cleared = True

    def load(self):
        return self.saved


def test_login_saves_credentials(monkeypatch) -> None:
    fake_store = _FakeStore()
    monkeypatch.setenv("WEBEX_TOKEN", "token123")
    monkeypatch.setattr(auth_commands, "resolve_profile", lambda: "default")
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda *args, **kwargs: fake_store)
    auth_commands.login(token=None)
    assert fake_store.saved is not None
    assert fake_store.saved.token == "token123"


def test_logout_clears_credentials(monkeypatch) -> None:
    fake_store = _FakeStore()
    monkeypatch.setattr(auth_commands, "resolve_profile", lambda: "default")
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda *args, **kwargs: fake_store)
    auth_commands.logout()
    assert fake_store.cleared is True


def test_login_json_emits_warning_for_fallback_backend(monkeypatch, capsys) -> None:
    fake_store = _FakeStore()
    monkeypatch.setenv("WEBEX_TOKEN", "token123")
    monkeypatch.setattr(auth_commands, "resolve_profile", lambda: "default")
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda *args, **kwargs: fake_store)
    auth_commands.login(token=None, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert "INSECURE_CREDENTIAL_STORE" in payload["warnings"]


def test_login_human_emits_warning_for_fallback_backend(monkeypatch, capsys) -> None:
    fake_store = _FakeStore()
    monkeypatch.setenv("WEBEX_TOKEN", "token123")
    monkeypatch.setattr(auth_commands, "resolve_profile", lambda: "default")
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda *args, **kwargs: fake_store)
    auth_commands.login(token=None, json_output=False)
    captured = capsys.readouterr()
    assert "Warning:" in captured.err and "plain-text file" in captured.err


def test_login_supports_env_token(monkeypatch) -> None:
    fake_store = _FakeStore()
    monkeypatch.setenv("WEBEX_TOKEN", "env-token")
    monkeypatch.setattr(auth_commands, "resolve_profile", lambda: "default")
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda *args, **kwargs: fake_store)
    auth_commands.login(token=None)
    assert fake_store.saved.token == "env-token"


def test_login_rejects_multiple_token_sources(monkeypatch) -> None:
    fake_store = _FakeStore()
    monkeypatch.setenv("WEBEX_TOKEN", "env-token")
    monkeypatch.setenv("WEBEX_ALLOW_INSECURE_TOKEN_ARG", "1")
    monkeypatch.setattr(auth_commands, "resolve_profile", lambda: "default")
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda *args, **kwargs: fake_store)
    with pytest.raises(typer.Exit):
        auth_commands.login(token="cli-token", json_output=True)


def test_login_rejects_cli_token_by_default(monkeypatch) -> None:
    fake_store = _FakeStore()
    monkeypatch.setattr(auth_commands, "resolve_profile", lambda: "default")
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda *args, **kwargs: fake_store)
    with pytest.raises(typer.Exit) as exc:
        auth_commands.login(token="cli-token", json_output=True)
    assert exc.value.exit_code == 2


def test_login_rejects_pat_sources_when_oauth_is_selected(monkeypatch) -> None:
    monkeypatch.setenv("WEBEX_TOKEN", "env-token")
    monkeypatch.setattr(auth_commands, "resolve_profile", lambda: "default")
    with pytest.raises(typer.Exit) as exc:
        auth_commands.login(oauth_device_flow=True, json_output=True)
    assert exc.value.exit_code == 2


def test_login_oauth_non_interactive_fails_fast(monkeypatch) -> None:
    monkeypatch.setattr(auth_commands, "resolve_profile", lambda: "default")
    with pytest.raises(typer.Exit) as exc:
        auth_commands.login(oauth_device_flow=True, non_interactive=True, oauth_client_id="client-id", json_output=True)
    assert exc.value.exit_code == 2


def test_login_oauth_device_flow_success(monkeypatch, capsys) -> None:
    fake_store = _FakeStore()
    monkeypatch.setattr(auth_commands, "resolve_profile", lambda: "default")
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda *args, **kwargs: fake_store)
    monkeypatch.setattr(
        auth_commands,
        "resolve_oauth_device_config",
        lambda **kwargs: OAuthDeviceConfig(
            client_id="client-id",
            device_authorize_url="https://example.test/device/authorize",
            token_url="https://example.test/device/token",
            scope="spark:all",
            poll_interval_seconds=5,
            timeout_seconds=600,
        ),
    )
    monkeypatch.setattr(
        auth_commands,
        "start_device_authorization",
        lambda config: {
            "device_code": "device-code",
            "user_code": "ABCD",
            "verification_uri": "https://example.test/device",
            "verification_uri_complete": "https://example.test/device?user_code=ABCD",
            "expires_in": 600,
            "interval_seconds": 5,
        },
    )
    monkeypatch.setattr(
        auth_commands,
        "poll_for_device_token",
        lambda config, *, device_code, interval_seconds: OAuthTokenBundle(
            access_token="oauth-access-token",
            refresh_token="oauth-refresh-token",
            expires_at="2026-03-05T00:00:00+00:00",
            scopes=["spark:all"],
        ),
    )

    auth_commands.login(oauth_device_flow=True, oauth_client_id="client-id", json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["auth_method"] == "oauth_device_flow"
    assert fake_store.saved.auth_type == "oauth"
    assert fake_store.saved.refresh_token == "oauth-refresh-token"
