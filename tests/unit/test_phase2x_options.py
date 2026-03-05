import json
import shutil
from pathlib import Path
import uuid

from webex_cli.config.options import resolve_option
from webex_cli.config.settings import Settings


def _temp_root() -> Path:
    root = Path(".test_tmp") / f"phase2x-options-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_resolve_option_precedence_cli_then_env_then_profile_then_global(monkeypatch) -> None:
    class _ProfileStore:
        def get_setting(self, profile_key: str, dotted_key: str):
            assert profile_key == "default"
            if dotted_key == "events.workers":
                return 3
            return None

    monkeypatch.setattr("webex_cli.config.options.resolve_profile", lambda: "default")
    monkeypatch.setattr("webex_cli.config.options.ProfileStore", _ProfileStore)
    monkeypatch.setattr("webex_cli.config.options.load_settings", lambda: Settings(events_workers=2))

    assert resolve_option(5, "WEBEX_EVENTS_WORKERS", "events.workers", "events_workers", default=1, value_type="int") == 5
    monkeypatch.setenv("WEBEX_EVENTS_WORKERS", "4")
    assert resolve_option(None, "WEBEX_EVENTS_WORKERS", "events.workers", "events_workers", default=1, value_type="int") == 4
    monkeypatch.delenv("WEBEX_EVENTS_WORKERS", raising=False)
    assert resolve_option(None, "WEBEX_EVENTS_WORKERS", "events.workers", "events_workers", default=1, value_type="int") == 3
    monkeypatch.setattr("webex_cli.config.options.ProfileStore", lambda: type("X", (), {"get_setting": lambda self, p, k: None})())
    assert resolve_option(None, "WEBEX_EVENTS_WORKERS", "events.workers", "events_workers", default=1, value_type="int") == 2
    monkeypatch.setattr("webex_cli.config.options.load_settings", lambda: Settings())
    assert resolve_option(None, "WEBEX_EVENTS_WORKERS", "events.workers", "events_workers", default=1, value_type="int") == 1


def test_resolve_option_supports_boolean_env_strings(monkeypatch) -> None:
    monkeypatch.setattr("webex_cli.config.options.resolve_profile", lambda: "default")
    monkeypatch.setattr("webex_cli.config.options.ProfileStore", lambda: type("X", (), {"get_setting": lambda self, p, k: None})())
    monkeypatch.setattr("webex_cli.config.options.load_settings", lambda: Settings())
    monkeypatch.setenv("WEBEX_SEARCH_LOCAL_INDEX_ENABLED", "true")
    assert resolve_option(
        None,
        "WEBEX_SEARCH_LOCAL_INDEX_ENABLED",
        "search.local_index_enabled",
        "search_local_index_enabled",
        default=False,
        value_type="bool",
    ) is True


def test_profile_store_paths_are_profile_scoped() -> None:
    from webex_cli.config import paths as paths_module

    root = _temp_root()
    try:
        import os

        previous = os.environ.get("APPDATA")
        os.environ["APPDATA"] = str(root)
        try:
            assert paths_module.events_queue_db_path("work").name == "queue.db"
            assert "work" in str(paths_module.events_queue_db_path("work"))
            assert paths_module.search_index_db_path("default").name == "transcript-index.db"
            assert paths_module.mutation_history_db_path("ops").name == "history.db"
        finally:
            if previous is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = previous
    finally:
        shutil.rmtree(root, ignore_errors=True)
