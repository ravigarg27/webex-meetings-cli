import shutil
from pathlib import Path
import uuid

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
