import json

import pytest
import typer

from webex_cli.commands import auth as auth_commands


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
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda: fake_store)
    auth_commands.login(token=None)
    assert fake_store.saved is not None
    assert fake_store.saved.token == "token123"


def test_logout_clears_credentials(monkeypatch) -> None:
    fake_store = _FakeStore()
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda: fake_store)
    auth_commands.logout()
    assert fake_store.cleared is True


def test_login_json_emits_warning_for_fallback_backend(monkeypatch, capsys) -> None:
    fake_store = _FakeStore()
    monkeypatch.setenv("WEBEX_TOKEN", "token123")
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda: fake_store)
    auth_commands.login(token=None, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert "INSECURE_CREDENTIAL_STORE" in payload["warnings"]


def test_login_human_emits_warning_for_fallback_backend(monkeypatch, capsys) -> None:
    fake_store = _FakeStore()
    monkeypatch.setenv("WEBEX_TOKEN", "token123")
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda: fake_store)
    auth_commands.login(token=None, json_output=False)
    captured = capsys.readouterr()
    assert "Warning:" in captured.err and "plain-text file" in captured.err


def test_login_supports_env_token(monkeypatch) -> None:
    fake_store = _FakeStore()
    monkeypatch.setenv("WEBEX_TOKEN", "env-token")
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda: fake_store)
    auth_commands.login(token=None)
    assert fake_store.saved.token == "env-token"


def test_login_rejects_multiple_token_sources(monkeypatch) -> None:
    fake_store = _FakeStore()
    monkeypatch.setenv("WEBEX_TOKEN", "env-token")
    monkeypatch.setenv("WEBEX_ALLOW_INSECURE_TOKEN_ARG", "1")
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda: fake_store)
    with pytest.raises(typer.Exit):
        auth_commands.login(token="cli-token", json_output=True)


def test_login_rejects_cli_token_by_default(monkeypatch) -> None:
    fake_store = _FakeStore()
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda: fake_store)
    with pytest.raises(typer.Exit) as exc:
        auth_commands.login(token="cli-token", json_output=True)
    assert exc.value.exit_code == 2
