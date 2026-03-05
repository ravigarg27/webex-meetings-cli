import json
import os
import shutil
import types
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
    monkeypatch.setenv("WEBEX_CREDENTIAL_FALLBACK_POLICY", "allow_file_fallback")
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
    monkeypatch.setenv("WEBEX_CREDENTIAL_FALLBACK_POLICY", "allow_file_fallback")
    monkeypatch.setenv("WEBEX_ALLOW_PLAINTEXT_REFRESH_TOKEN", "1")
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


def test_ci_strict_blocks_file_fallback_when_non_interactive(monkeypatch) -> None:
    tmp_path = Path(".test_tmp") / f"credentials-{uuid.uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(CredentialStore, "_keyring_available", lambda self: False)
    monkeypatch.delenv("CI", raising=False)

    class _NoTty:
        @staticmethod
        def isatty() -> bool:
            return False

    monkeypatch.setattr(credentials_module.sys, "stdin", _NoTty())
    monkeypatch.setattr(credentials_module.sys, "stdout", _NoTty())
    try:
        with pytest.raises(CliError) as exc:
            CredentialStore().save(CredentialRecord(token="token123"))
        assert exc.value.code == DomainCode.VALIDATION_ERROR
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_load_prefers_backend_from_metadata_to_avoid_split_brain(monkeypatch) -> None:
    tmp_path = Path(".test_tmp") / f"credentials-{uuid.uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(CredentialStore, "_keyring_available", lambda self: True)
    monkeypatch.setenv("WEBEX_CREDENTIAL_FALLBACK_POLICY", "allow_file_fallback")

    keyring_data: dict[tuple[str, str], str] = {}

    def _set_password(service, account, value):
        keyring_data[(service, account)] = value

    def _get_password(service, account):
        return keyring_data.get((service, account))

    def _delete_password(service, account):
        keyring_data.pop((service, account), None)

    monkeypatch.setitem(
        credentials_module.sys.modules,
        "keyring",
        types.SimpleNamespace(
            set_password=_set_password,
            get_password=_get_password,
            delete_password=_delete_password,
        ),
    )
    try:
        path = tmp_path / "credentials.json"
        path.write_text(json.dumps({"default": {"token": "fallback-token"}}), encoding="utf-8")
        (tmp_path / "default-metadata.json").write_text(
            json.dumps({"credential_backend": "file_fallback", "auth_type": "pat", "scopes": []}),
            encoding="utf-8",
        )
        keyring_data[("webex-cli", "default")] = "stale-keyring-token"

        loaded = CredentialStore().load()
        assert loaded.token == "fallback-token"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
        credentials_module.sys.modules.pop("keyring", None)


def test_keyring_partial_save_falls_back_and_loads_fallback_bundle(monkeypatch) -> None:
    tmp_path = Path(".test_tmp") / f"credentials-{uuid.uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(CredentialStore, "_keyring_available", lambda self: True)
    monkeypatch.setenv("WEBEX_CREDENTIAL_FALLBACK_POLICY", "allow_file_fallback")
    monkeypatch.setenv("WEBEX_ALLOW_PLAINTEXT_REFRESH_TOKEN", "1")

    keyring_data: dict[tuple[str, str], str] = {}

    def _set_password(service, account, value):
        if account.endswith(":refresh"):
            raise RuntimeError("refresh write failed")
        keyring_data[(service, account)] = value

    def _get_password(service, account):
        return keyring_data.get((service, account))

    def _delete_password(service, account):
        keyring_data.pop((service, account), None)

    monkeypatch.setitem(
        credentials_module.sys.modules,
        "keyring",
        types.SimpleNamespace(
            set_password=_set_password,
            get_password=_get_password,
            delete_password=_delete_password,
        ),
    )
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
        assert ("webex-cli", "default") not in keyring_data

        loaded = store.load()
        assert loaded.token == "access-token"
        assert loaded.refresh_token == "refresh-token"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
        credentials_module.sys.modules.pop("keyring", None)


def test_non_windows_fallback_does_not_persist_refresh_token_by_default(monkeypatch) -> None:
    if os.name == "nt":
        pytest.skip("Non-Windows-only behavior.")
    tmp_path = Path(".test_tmp") / f"credentials-{uuid.uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(CredentialStore, "_keyring_available", lambda self: False)
    monkeypatch.setenv("WEBEX_CREDENTIAL_FALLBACK_POLICY", "allow_file_fallback")
    monkeypatch.delenv("WEBEX_ALLOW_PLAINTEXT_REFRESH_TOKEN", raising=False)
    try:
        store = CredentialStore()
        store.save(
            CredentialRecord(
                token="access-token",
                auth_type="oauth",
                refresh_token="refresh-token",
                expires_at="2026-03-05T00:00:00+00:00",
                scopes=["spark:all"],
            )
        )
        loaded = store.load()
        assert loaded.refresh_token is None
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
