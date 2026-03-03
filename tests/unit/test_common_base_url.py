import pytest

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
