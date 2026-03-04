import shutil
import sys
from pathlib import Path
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolate_cli_config_home(monkeypatch: pytest.MonkeyPatch):
    base = ROOT / "temp_work" / "config-homes"
    base.mkdir(parents=True, exist_ok=True)
    config_home = base / f"config-home-{uuid.uuid4().hex}"
    config_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("APPDATA", str(config_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    yield
    shutil.rmtree(config_home, ignore_errors=True)
