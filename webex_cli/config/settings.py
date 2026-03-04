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
    oauth_client_id: str | None = None
    oauth_device_authorize_url: str | None = None
    oauth_token_url: str | None = None
    oauth_scope: str | None = None
    oauth_poll_interval_seconds: int | None = None
    oauth_timeout_seconds: int | None = None


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
    oauth_client_id = data.get("oauth_client_id")
    oauth_device_authorize_url = data.get("oauth_device_authorize_url")
    oauth_token_url = data.get("oauth_token_url")
    oauth_scope = data.get("oauth_scope")
    oauth_poll_interval_seconds = data.get("oauth_poll_interval_seconds")
    oauth_timeout_seconds = data.get("oauth_timeout_seconds")
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
    if oauth_client_id is not None and not isinstance(oauth_client_id, str):
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "`oauth_client_id` must be a string when set.",
            details={"path": str(path)},
        )
    if oauth_device_authorize_url is not None and not isinstance(oauth_device_authorize_url, str):
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "`oauth_device_authorize_url` must be a string when set.",
            details={"path": str(path)},
        )
    if oauth_token_url is not None and not isinstance(oauth_token_url, str):
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "`oauth_token_url` must be a string when set.",
            details={"path": str(path)},
        )
    if oauth_scope is not None and not isinstance(oauth_scope, str):
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "`oauth_scope` must be a string when set.",
            details={"path": str(path)},
        )
    if oauth_poll_interval_seconds is not None and not isinstance(oauth_poll_interval_seconds, int):
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "`oauth_poll_interval_seconds` must be an integer when set.",
            details={"path": str(path)},
        )
    if oauth_timeout_seconds is not None and not isinstance(oauth_timeout_seconds, int):
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "`oauth_timeout_seconds` must be an integer when set.",
            details={"path": str(path)},
        )
    return Settings(
        api_base_url=api_base_url,
        default_tz=default_tz,
        oauth_client_id=oauth_client_id,
        oauth_device_authorize_url=oauth_device_authorize_url,
        oauth_token_url=oauth_token_url,
        oauth_scope=oauth_scope,
        oauth_poll_interval_seconds=oauth_poll_interval_seconds,
        oauth_timeout_seconds=oauth_timeout_seconds,
    )


def save_settings(settings: Settings) -> None:
    cfg = config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    path = settings_path()
    payload = {
        "api_base_url": settings.api_base_url,
        "default_tz": settings.default_tz,
        "oauth_client_id": settings.oauth_client_id,
        "oauth_device_authorize_url": settings.oauth_device_authorize_url,
        "oauth_token_url": settings.oauth_token_url,
        "oauth_scope": settings.oauth_scope,
        "oauth_poll_interval_seconds": settings.oauth_poll_interval_seconds,
        "oauth_timeout_seconds": settings.oauth_timeout_seconds,
    }
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
