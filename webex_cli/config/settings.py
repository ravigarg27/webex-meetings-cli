from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any

from webex_cli.config.paths import config_dir, settings_path
from webex_cli.errors import CliError, DomainCode


@dataclass
class Settings:
    api_base_url: str = "https://webexapis.com"
    default_tz: str | None = None


def load_settings() -> Settings:
    path = settings_path()
    if not path.exists():
        return Settings()
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "Config file is invalid JSON.",
            details={"path": str(path)},
        ) from exc
    if not isinstance(data, dict):
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "Config file must be a JSON object.",
            details={"path": str(path)},
        )
    api_base_url = data.get("api_base_url", "https://webexapis.com")
    default_tz = data.get("default_tz")
    if not isinstance(api_base_url, str):
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "`api_base_url` must be a string.",
            details={"path": str(path)},
        )
    if default_tz is not None and not isinstance(default_tz, str):
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "`default_tz` must be a string when set.",
            details={"path": str(path)},
        )
    return Settings(
        api_base_url=api_base_url,
        default_tz=default_tz,
    )


def save_settings(settings: Settings) -> None:
    cfg = config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    path = settings_path()
    payload = {"api_base_url": settings.api_base_url, "default_tz": settings.default_tz}
    _write_json_atomic(path, payload)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, indent=2)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        Path(tmp_path).replace(path)
        if os.name != "nt":
            os.chmod(path, 0o600)
    finally:
        tmp = Path(tmp_path)
        if tmp.exists():
            tmp.unlink(missing_ok=True)
