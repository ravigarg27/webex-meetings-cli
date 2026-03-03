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

    def clear(self):
        self.cleared = True


def test_login_saves_credentials(monkeypatch) -> None:
    fake_store = _FakeStore()
    monkeypatch.setattr(auth_commands, "build_client", lambda token=None: _FakeClient())
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda: fake_store)
    auth_commands.login(token="token123")
    assert fake_store.saved is not None
    assert fake_store.saved.token == "token123"


def test_logout_clears_credentials(monkeypatch) -> None:
    fake_store = _FakeStore()
    monkeypatch.setattr(auth_commands, "CredentialStore", lambda: fake_store)
    auth_commands.logout()
    assert fake_store.cleared is True

