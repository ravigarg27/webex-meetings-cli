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


def profiles_path() -> Path:
    return config_dir() / "profiles.json"


def profile_migration_marker_path() -> Path:
    return config_dir() / "migration-profile-1.1.json"


def legacy_metadata_path() -> Path:
    return config_dir() / "metadata.json"


def capabilities_cache_path() -> Path:
    return config_dir() / "capabilities.json"


def profile_events_dir(profile: str) -> Path:
    return config_dir() / "events" / profile


def profile_search_dir(profile: str) -> Path:
    return config_dir() / "search" / profile


def profile_mutations_dir(profile: str) -> Path:
    return config_dir() / "mutations" / profile


def events_queue_db_path(profile: str) -> Path:
    return profile_events_dir(profile) / "queue.db"


def events_dedupe_db_path(profile: str) -> Path:
    return profile_events_dir(profile) / "dedupe.db"


def events_dlq_db_path(profile: str) -> Path:
    return profile_events_dir(profile) / "dlq.db"


def events_checkpoint_db_path(profile: str) -> Path:
    return profile_events_dir(profile) / "checkpoints.db"


def events_meta_path(profile: str) -> Path:
    return profile_events_dir(profile) / "meta.json"


def search_index_db_path(profile: str) -> Path:
    return profile_search_dir(profile) / "transcript-index.db"


def search_meta_path(profile: str) -> Path:
    return profile_search_dir(profile) / "meta.json"


def mutation_history_db_path(profile: str) -> Path:
    return profile_mutations_dir(profile) / "history.db"


def mutation_idempotency_cache_path(profile: str) -> Path:
    return profile_mutations_dir(profile) / "idempotency-cache.json"
