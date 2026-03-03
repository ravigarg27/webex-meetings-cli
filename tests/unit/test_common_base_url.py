import pytest

from webex_cli.commands import common as common_commands
from webex_cli.commands.common import resolve_base_url
from webex_cli.errors import CliError, DomainCode


def test_resolve_base_url_uses_env(monkeypatch) -> None:
    monkeypatch.setenv("WEBEX_API_BASE_URL", "https://example.test")
    assert resolve_base_url() == "https://example.test"


def test_resolve_base_url_rejects_non_https(monkeypatch) -> None:
    monkeypatch.setenv("WEBEX_API_BASE_URL", "http://insecure.test")
    with pytest.raises(CliError) as exc:
        resolve_base_url()
    assert exc.value.code == DomainCode.VALIDATION_ERROR


def test_resolve_effective_timezone_prefers_cli_tz(monkeypatch) -> None:
    class _Settings:
        default_tz = "America/New_York"

    monkeypatch.setattr(common_commands, "load_settings", lambda: _Settings())
    assert common_commands.resolve_effective_timezone("UTC") == "UTC"


def test_resolve_effective_timezone_uses_profile_default(monkeypatch) -> None:
    class _Settings:
        default_tz = "America/New_York"

    monkeypatch.setattr(common_commands, "load_settings", lambda: _Settings())
    assert common_commands.resolve_effective_timezone(None) == "America/New_York"
