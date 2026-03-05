import pytest
import httpx

from webex_cli.commands import common as common_commands
from webex_cli.config.credentials import CredentialRecord
from webex_cli.config.settings import Settings
from webex_cli.errors import CliError, DomainCode
from webex_cli.oauth import OAuthTokenBundle, resolve_oauth_device_config
from webex_cli import oauth as oauth_module


class _FakeCredentialStore:
    def __init__(self, profile: str = "default") -> None:
        self.profile = profile
        self.saved_record: CredentialRecord | None = None
        self.invalid_reason: str | None = None
        self.record = CredentialRecord(
            token="old-access-token",
            auth_type="oauth",
            refresh_token="refresh-token",
            expires_at="2000-01-01T00:00:00+00:00",
            scopes=["spark:all"],
        )

    def load(self) -> CredentialRecord:
        return self.record

    def save(self, record: CredentialRecord) -> str:
        self.saved_record = record
        self.record = record
        return "file_fallback"

    def mark_invalid(self, reason: str) -> None:
        self.invalid_reason = reason
        self.record.invalid_reason = reason

    def clear_invalid(self) -> None:
        self.invalid_reason = None
        self.record.invalid_reason = None


def test_resolve_oauth_device_config_precedence(monkeypatch) -> None:
    monkeypatch.setattr(
        oauth_module,
        "load_settings",
        lambda: Settings(
            oauth_client_id="cfg-client",
            oauth_device_authorize_url="https://cfg.example.test/authorize",
            oauth_token_url="https://cfg.example.test/token",
            oauth_scope="spark:all spark:kms",
            oauth_poll_interval_seconds=9,
            oauth_timeout_seconds=700,
        ),
    )
    monkeypatch.setenv("WEBEX_OAUTH_CLIENT_ID", "env-client")
    monkeypatch.setenv("WEBEX_OAUTH_TOKEN_URL", "https://env.example.test/token")

    config = resolve_oauth_device_config(
        client_id="flag-client",
        device_authorize_url="https://flag.example.test/authorize",
        poll_interval_seconds=7,
    )

    assert config.client_id == "flag-client"
    assert config.device_authorize_url == "https://flag.example.test/authorize"
    assert config.token_url == "https://env.example.test/token"
    assert config.scope == "spark:all spark:kms"
    assert config.poll_interval_seconds == 7
    assert config.timeout_seconds == 700


def test_load_credential_record_refreshes_expiring_oauth(monkeypatch) -> None:
    fake_store = _FakeCredentialStore()
    fake_store.record.oauth_client_id = "persisted-client-id"
    fake_store.record.oauth_token_url = "https://token.example.test"
    captured: dict[str, object] = {}
    monkeypatch.setattr(common_commands, "resolve_profile", lambda: "default")
    monkeypatch.setattr(common_commands, "CredentialStore", lambda profile="default": fake_store)
    monkeypatch.setattr(
        common_commands,
        "resolve_oauth_device_config",
        lambda **kwargs: captured.update(kwargs) or object(),
    )
    monkeypatch.setattr(common_commands, "is_expiring_soon", lambda expires_at: True)
    monkeypatch.setattr(
        common_commands,
        "refresh_access_token",
        lambda config, refresh_token: OAuthTokenBundle(
            access_token="new-access-token",
            refresh_token="new-refresh-token",
            expires_at="2027-01-01T00:00:00+00:00",
            scopes=["spark:all"],
        ),
    )

    record = common_commands.load_credential_record()

    assert record.token == "new-access-token"
    assert fake_store.saved_record is not None
    assert fake_store.saved_record.refresh_token == "new-refresh-token"
    assert fake_store.invalid_reason is None
    assert captured["client_id"] == "persisted-client-id"
    assert captured["token_url"] == "https://token.example.test"


def test_load_credential_record_marks_invalid_on_refresh_failure(monkeypatch) -> None:
    fake_store = _FakeCredentialStore()
    monkeypatch.setattr(common_commands, "resolve_profile", lambda: "default")
    monkeypatch.setattr(common_commands, "CredentialStore", lambda profile="default": fake_store)
    monkeypatch.setattr(common_commands, "resolve_oauth_device_config", lambda **kwargs: object())
    monkeypatch.setattr(common_commands, "is_expiring_soon", lambda expires_at: True)

    def _raise_refresh(config, refresh_token):
        raise CliError(
            DomainCode.AUTH_INVALID,
            "refresh failed",
            details={"auth_cause": "revoked"},
        )

    monkeypatch.setattr(common_commands, "refresh_access_token", _raise_refresh)

    with pytest.raises(CliError) as exc:
        common_commands.load_credential_record()
    assert exc.value.code == DomainCode.AUTH_INVALID
    assert fake_store.invalid_reason == "revoked"


def test_resolve_oauth_device_config_rejects_blank_client_id(monkeypatch) -> None:
    monkeypatch.setattr(oauth_module, "load_settings", lambda: Settings())
    with pytest.raises(CliError) as exc:
        resolve_oauth_device_config(client_id="   ")
    assert exc.value.code == DomainCode.VALIDATION_ERROR


def test_resolve_oauth_device_config_rejects_zero_poll_interval_and_timeout(monkeypatch) -> None:
    monkeypatch.setattr(oauth_module, "load_settings", lambda: Settings())
    with pytest.raises(CliError) as poll_exc:
        resolve_oauth_device_config(client_id="client-id", poll_interval_seconds=0)
    assert poll_exc.value.code == DomainCode.VALIDATION_ERROR
    with pytest.raises(CliError) as timeout_exc:
        resolve_oauth_device_config(client_id="client-id", timeout_seconds=0)
    assert timeout_exc.value.code == DomainCode.VALIDATION_ERROR


def test_start_device_authorization_maps_invalid_client_as_validation(monkeypatch) -> None:
    config = oauth_module.OAuthDeviceConfig(
        client_id="bad-client",
        device_authorize_url="https://example.test/device/authorize",
        token_url="https://example.test/device/token",
        scope="spark:all",
        poll_interval_seconds=5,
        timeout_seconds=60,
    )
    request = httpx.Request("POST", config.device_authorize_url)

    def _fake_post(self, url, data):
        return httpx.Response(
            400,
            request=request,
            json={"error": "invalid_client", "error_description": "client not found"},
        )

    monkeypatch.setattr(httpx.Client, "post", _fake_post, raising=True)
    with pytest.raises(CliError) as exc:
        oauth_module.start_device_authorization(config)
    assert exc.value.code == DomainCode.VALIDATION_ERROR
