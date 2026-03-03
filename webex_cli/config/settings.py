from __future__ import annotations

import json
from dataclasses import dataclass

from webex_cli.config.paths import config_dir, settings_path


@dataclass
class Settings:
    api_base_url: str = "https://webexapis.com"
    default_tz: str | None = None


def load_settings() -> Settings:
    path = settings_path()
    if not path.exists():
        return Settings()
    data = json.loads(path.read_text(encoding="utf-8"))
    return Settings(
        api_base_url=data.get("api_base_url", "https://webexapis.com"),
        default_tz=data.get("default_tz"),
    )


def save_settings(settings: Settings) -> None:
    cfg = config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    path = settings_path()
    payload = {"api_base_url": settings.api_base_url, "default_tz": settings.default_tz}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
