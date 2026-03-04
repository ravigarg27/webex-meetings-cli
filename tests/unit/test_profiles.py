import json
from pathlib import Path
import shutil
import uuid

import pytest

from webex_cli.commands import common as common_commands
from webex_cli.commands import profile as profile_commands
from webex_cli.config import credentials as credentials_module
from webex_cli.config import profiles as profiles_module
from webex_cli.config.profiles import ProfileStore
from webex_cli.config.settings import Settings
from webex_cli.errors import CliError, DomainCode
from webex_cli.runtime import use_profile


def _temp_root() -> Path:
    root = Path(".test_tmp") / f"profiles-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _patch_profile_store(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(profiles_module, "config_dir", lambda: root)
    monkeypatch.setattr(profiles_module, "profiles_path", lambda: root / "profiles.json")
    monkeypatch.setattr(profiles_module, "fallback_credentials_path", lambda: root / "credentials.json")
    monkeypatch.setattr(profiles_module, "legacy_metadata_path", lambda: root / "metadata.json")
    monkeypatch.setattr(profiles_module, "profile_migration_marker_path", lambda: root / "migration-profile-1.1.json")
    monkeypatch.setattr(profiles_module, "load_settings", lambda: Settings(default_tz="UTC"))


def test_profile_store_initializes_default_profile(monkeypatch) -> None:
    root = _temp_root()
    _patch_profile_store(monkeypatch, root)
    try:
        registry = ProfileStore().ensure_initialized()
        assert registry.active_profile == "default"
        assert "default" in registry.profiles
        assert registry.profiles["default"].default_tz == "UTC"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_profile_store_rejects_duplicate_case_insensitive_name(monkeypatch) -> None:
    root = _temp_root()
    _patch_profile_store(monkeypatch, root)
    try:
        store = ProfileStore()
        store.ensure_initialized()
        store.create_profile("Work", default_tz=None, site_url=None)
        with pytest.raises(CliError) as exc:
            store.create_profile("work", default_tz=None, site_url=None)
        assert exc.value.code == DomainCode.VALIDATION_ERROR
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_profile_store_delete_active_is_blocked(monkeypatch) -> None:
    root = _temp_root()
    _patch_profile_store(monkeypatch, root)
    try:
        store = ProfileStore()
        store.ensure_initialized()
        with pytest.raises(CliError) as exc:
            store.delete_profile("default")
        assert exc.value.code == DomainCode.VALIDATION_ERROR
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_resolve_profile_precedence_runtime_over_env(monkeypatch) -> None:
    root = _temp_root()
    _patch_profile_store(monkeypatch, root)
    try:
        store = ProfileStore()
        store.ensure_initialized()
        store.create_profile("work", default_tz=None, site_url=None)
        monkeypatch.setenv("WEBEX_PROFILE", "work")
        assert common_commands.resolve_profile() == "work"
        with use_profile("default"):
            assert common_commands.resolve_profile() == "default"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_resolve_profile_env_unknown_fails_not_found(monkeypatch) -> None:
    root = _temp_root()
    _patch_profile_store(monkeypatch, root)
    try:
        ProfileStore().ensure_initialized()
        monkeypatch.setenv("WEBEX_PROFILE", "missing")
        with pytest.raises(CliError) as exc:
            common_commands.resolve_profile()
        assert exc.value.code == DomainCode.NOT_FOUND
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_profile_commands_create_use_show_and_delete(monkeypatch, capsys) -> None:
    root = _temp_root()
    _patch_profile_store(monkeypatch, root)
    cleared: list[str] = []

    class _FakeCredentialStore:
        def __init__(self, profile: str = "default") -> None:
            self.profile = profile

        def clear(self) -> None:
            cleared.append(self.profile)

    monkeypatch.setattr(credentials_module, "CredentialStore", _FakeCredentialStore)
    try:
        profile_commands.create_profile(
            name="work",
            default_tz="UTC",
            site_url="https://site.example.test",
            json_output=True,
        )
        create_payload = json.loads(capsys.readouterr().out)
        assert create_payload["ok"] is True
        assert create_payload["data"]["name"] == "work"

        profile_commands.use_profile(name="work", json_output=True)
        use_payload = json.loads(capsys.readouterr().out)
        assert use_payload["data"]["is_active"] is True
        assert use_payload["data"]["key"] == "work"

        profile_commands.show_profile(name=None, json_output=True)
        show_payload = json.loads(capsys.readouterr().out)
        assert show_payload["data"]["key"] == "work"
        assert show_payload["data"]["is_active"] is True

        profile_commands.use_profile(name="default", json_output=True)
        _ = json.loads(capsys.readouterr().out)

        profile_commands.delete_profile(name="work", json_output=True)
        delete_payload = json.loads(capsys.readouterr().out)
        assert delete_payload["data"]["key"] == "work"
        assert "work" in cleared
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_profile_store_migrates_legacy_credential_layout(monkeypatch) -> None:
    root = _temp_root()
    _patch_profile_store(monkeypatch, root)
    try:
        (root / "credentials.json").write_text('{"token":"legacy-token"}', encoding="utf-8")
        (root / "metadata.json").write_text('{"credential_backend":"file_fallback"}', encoding="utf-8")

        ProfileStore().ensure_initialized()

        migrated_credentials = json.loads((root / "credentials.json").read_text(encoding="utf-8"))
        assert migrated_credentials["default"]["token"] == "legacy-token"
        migrated_metadata = json.loads((root / "default-metadata.json").read_text(encoding="utf-8"))
        assert migrated_metadata["credential_backend"] == "file_fallback"
        marker = json.loads((root / "migration-profile-1.1.json").read_text(encoding="utf-8"))
        assert marker["version"] == "1.1"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_profile_store_migration_rolls_back_on_failure(monkeypatch) -> None:
    root = _temp_root()
    _patch_profile_store(monkeypatch, root)
    original_payload = {"token": "legacy-token"}
    (root / "credentials.json").write_text(json.dumps(original_payload), encoding="utf-8")

    original_writer = ProfileStore._write_json_atomic

    def _failing_writer(path: Path, payload: dict) -> None:
        if path.name == "migration-profile-1.1.json":
            raise OSError("marker write failed")
        original_writer(path, payload)

    monkeypatch.setattr(ProfileStore, "_write_json_atomic", staticmethod(_failing_writer))
    try:
        with pytest.raises(CliError) as exc:
            ProfileStore().ensure_initialized()
        assert exc.value.code == DomainCode.INTERNAL_ERROR
        restored = json.loads((root / "credentials.json").read_text(encoding="utf-8"))
        assert restored == original_payload
    finally:
        shutil.rmtree(root, ignore_errors=True)
