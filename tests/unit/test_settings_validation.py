import shutil
from pathlib import Path
import uuid
import json

import pytest

from webex_cli.config import settings as settings_module
from webex_cli.errors import CliError, DomainCode


def _temp_settings_path() -> tuple[Path, Path]:
    root = Path(".test_tmp") / f"settings-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root, root / "config.json"


def test_load_settings_rejects_invalid_json(monkeypatch) -> None:
    root, path = _temp_settings_path()
    try:
        path.write_text("{bad-json", encoding="utf-8")
        monkeypatch.setattr(settings_module, "settings_path", lambda: path)
        with pytest.raises(CliError) as exc:
            settings_module.load_settings()
        assert exc.value.code == DomainCode.VALIDATION_ERROR
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_load_settings_rejects_non_object_json(monkeypatch) -> None:
    root, path = _temp_settings_path()
    try:
        path.write_text('["not", "an", "object"]', encoding="utf-8")
        monkeypatch.setattr(settings_module, "settings_path", lambda: path)
        with pytest.raises(CliError) as exc:
            settings_module.load_settings()
        assert exc.value.code == DomainCode.VALIDATION_ERROR
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_save_settings_writes_json_atomically(monkeypatch) -> None:
    root, path = _temp_settings_path()
    try:
        monkeypatch.setattr(settings_module, "config_dir", lambda: root)
        monkeypatch.setattr(settings_module, "settings_path", lambda: path)
        settings_module.save_settings(
            settings_module.Settings(api_base_url="https://webexapis.com", default_tz="UTC")
        )
        loaded = settings_module.load_settings()
        assert loaded.api_base_url == "https://webexapis.com"
        assert loaded.default_tz == "UTC"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_save_settings_omits_none_fields(monkeypatch) -> None:
    root, path = _temp_settings_path()
    try:
        monkeypatch.setattr(settings_module, "config_dir", lambda: root)
        monkeypatch.setattr(settings_module, "settings_path", lambda: path)
        settings_module.save_settings(settings_module.Settings(api_base_url="https://webexapis.com"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload == {"api_base_url": "https://webexapis.com"}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_load_settings_supports_phase2x_keys(monkeypatch) -> None:
    root, path = _temp_settings_path()
    try:
        path.write_text(
            json.dumps(
                {
                    "api_base_url": "https://webexapis.com",
                    "events_workers": 4,
                    "events_ingress_public_base_url": "https://example.test",
                    "search_local_index_enabled": True,
                    "mutations_idempotency_retention_days": 30,
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(settings_module, "settings_path", lambda: path)
        loaded = settings_module.load_settings()
        assert loaded.events_workers == 4
        assert loaded.events_ingress_public_base_url == "https://example.test"
        assert loaded.search_local_index_enabled is True
        assert loaded.mutations_idempotency_retention_days == 30
    finally:
        shutil.rmtree(root, ignore_errors=True)
