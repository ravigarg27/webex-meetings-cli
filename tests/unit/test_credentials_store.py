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
        assert payload["default"]["token"] == "token123"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
