from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    if os.name == "nt":
        root = os.environ.get("APPDATA")
        if not root:
            root = str(Path.home() / "AppData" / "Roaming")
        return Path(root) / "webex-cli"
    root = os.environ.get("XDG_CONFIG_HOME")
    if root:
        return Path(root) / "webex-cli"
    return Path.home() / ".config" / "webex-cli"


def settings_path() -> Path:
    return config_dir() / "config.json"


def fallback_credentials_path() -> Path:
    return config_dir() / "credentials.json"

