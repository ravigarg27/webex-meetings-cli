import json
import shutil
from pathlib import Path
import uuid

import pytest

from webex_cli.config import credentials as credentials_module
from webex_cli.config.credentials import CredentialRecord, CredentialStore
from webex_cli.errors import CliError, DomainCode


def _patch_paths(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(credentials_module, "config_dir", lambda: root)
    monkeypatch.setattr(credentials_module, "fallback_credentials_path", lambda: root / "credentials.json")


def test_load_handles_corrupt_fallback_file(monkeypatch) -> None:
    tmp_path = Path(".test_tmp") / f"credentials-{uuid.uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(CredentialStore, "_keyring_available", lambda self: False)
    try:
        (tmp_path / "credentials.json").write_text("{not-json", encoding="utf-8")

        with pytest.raises(CliError) as exc:
            CredentialStore().load()
        assert exc.value.code == DomainCode.AUTH_REQUIRED
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_save_recovers_from_corrupt_fallback_file(monkeypatch) -> None:
    tmp_path = Path(".test_tmp") / f"credentials-{uuid.uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(CredentialStore, "_keyring_available", lambda self: False)
    try:
        path = tmp_path / "credentials.json"
        path.write_text("{not-json", encoding="utf-8")

        store = CredentialStore()
        backend = store.save(CredentialRecord(token="token123"))

        assert backend == "file_fallback"
        payload = json.loads(path.read_text(encoding="utf-8"))
        item = payload["default"]
        assert "token" in item or "token_dpapi" in item
        assert store.load().token == "token123"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_save_and_load_oauth_bundle_in_fallback_store(monkeypatch) -> None:
    tmp_path = Path(".test_tmp") / f"credentials-{uuid.uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(CredentialStore, "_keyring_available", lambda self: False)
    try:
        store = CredentialStore()
        backend = store.save(
            CredentialRecord(
                token="access-token",
                auth_type="oauth",
                refresh_token="refresh-token",
                expires_at="2026-03-05T00:00:00+00:00",
                scopes=["spark:all"],
            )
        )
        assert backend == "file_fallback"

        loaded = store.load()
        assert loaded.token == "access-token"
        assert loaded.auth_type == "oauth"
        assert loaded.refresh_token == "refresh-token"
        assert loaded.expires_at == "2026-03-05T00:00:00+00:00"
        assert loaded.scopes == ["spark:all"]
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_ci_strict_blocks_file_fallback_in_ci(monkeypatch) -> None:
    tmp_path = Path(".test_tmp") / f"credentials-{uuid.uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(CredentialStore, "_keyring_available", lambda self: False)
    monkeypatch.setenv("CI", "true")
    try:
        store = CredentialStore()
        with pytest.raises(CliError) as exc:
            store.save(CredentialRecord(token="token123"))
        assert exc.value.code == DomainCode.VALIDATION_ERROR
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_allow_file_fallback_policy_overrides_ci_strict(monkeypatch) -> None:
    tmp_path = Path(".test_tmp") / f"credentials-{uuid.uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(CredentialStore, "_keyring_available", lambda self: False)
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("WEBEX_CREDENTIAL_FALLBACK_POLICY", "allow_file_fallback")
    try:
        backend = CredentialStore().save(CredentialRecord(token="token123"))
        assert backend == "file_fallback"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
