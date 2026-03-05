from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any

from webex_cli.config.paths import config_dir, settings_path
from webex_cli.errors import CliError, DomainCode
from webex_cli.utils.files import write_json_atomic

_SETTINGS_CACHE: Settings | None = None
_SETTINGS_CACHE_KEY: tuple[str, bool, int | None] | None = None
_SETTINGS_CACHE_LOCK = threading.RLock()


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
    events_workers: int | None = None
    events_shutdown_timeout_sec: int | None = None
    events_dedupe_ttl_hours: int | None = None
    events_dlq_retention_days: int | None = None
    events_ingress_bind_host: str | None = None
    events_ingress_bind_port: int | None = None
    events_ingress_public_base_url: str | None = None
    events_ingress_path: str | None = None
    events_ingress_secret_env: str | None = None
    search_local_index_enabled: bool | None = None
    search_local_index_stale_hours: int | None = None
    search_local_index_prune_days: int | None = None
    mutations_idempotency_retention_days: int | None = None
    phase2x_disable_mutations: bool | None = None


def _validate_optional_str(path: Path, key: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            f"`{key}` must be a string when set.",
            details={"path": str(path)},
        )
    return value


def _validate_optional_int(path: Path, key: str, value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            f"`{key}` must be an integer when set.",
            details={"path": str(path)},
        )
    return value


def _validate_optional_bool(path: Path, key: str, value: Any) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            f"`{key}` must be a boolean when set.",
            details={"path": str(path)},
        )
    return value


def _settings_cache_key(path: Path) -> tuple[str, bool, int | None]:
    if not path.exists():
        return (str(path), False, None)
    try:
        stat = path.stat()
    except OSError:
        return (str(path), True, None)
    return (str(path), True, stat.st_mtime_ns)


def load_settings() -> Settings:
    global _SETTINGS_CACHE, _SETTINGS_CACHE_KEY
    with _SETTINGS_CACHE_LOCK:
        path = settings_path()
        cache_key = _settings_cache_key(path)
        if _SETTINGS_CACHE is not None and _SETTINGS_CACHE_KEY == cache_key:
            return _SETTINGS_CACHE
        if not path.exists():
            settings = Settings()
            _SETTINGS_CACHE = settings
            _SETTINGS_CACHE_KEY = cache_key
            return settings
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
        default_tz = _validate_optional_str(path, "default_tz", data.get("default_tz"))
        oauth_client_id = _validate_optional_str(path, "oauth_client_id", data.get("oauth_client_id"))
        oauth_device_authorize_url = _validate_optional_str(path, "oauth_device_authorize_url", data.get("oauth_device_authorize_url"))
        oauth_token_url = _validate_optional_str(path, "oauth_token_url", data.get("oauth_token_url"))
        oauth_scope = _validate_optional_str(path, "oauth_scope", data.get("oauth_scope"))
        oauth_poll_interval_seconds = _validate_optional_int(path, "oauth_poll_interval_seconds", data.get("oauth_poll_interval_seconds"))
        oauth_timeout_seconds = _validate_optional_int(path, "oauth_timeout_seconds", data.get("oauth_timeout_seconds"))
        events_workers = _validate_optional_int(path, "events_workers", data.get("events_workers"))
        events_shutdown_timeout_sec = _validate_optional_int(path, "events_shutdown_timeout_sec", data.get("events_shutdown_timeout_sec"))
        events_dedupe_ttl_hours = _validate_optional_int(path, "events_dedupe_ttl_hours", data.get("events_dedupe_ttl_hours"))
        events_dlq_retention_days = _validate_optional_int(path, "events_dlq_retention_days", data.get("events_dlq_retention_days"))
        events_ingress_bind_host = _validate_optional_str(path, "events_ingress_bind_host", data.get("events_ingress_bind_host"))
        events_ingress_bind_port = _validate_optional_int(path, "events_ingress_bind_port", data.get("events_ingress_bind_port"))
        events_ingress_public_base_url = _validate_optional_str(path, "events_ingress_public_base_url", data.get("events_ingress_public_base_url"))
        events_ingress_path = _validate_optional_str(path, "events_ingress_path", data.get("events_ingress_path"))
        events_ingress_secret_env = _validate_optional_str(path, "events_ingress_secret_env", data.get("events_ingress_secret_env"))
        search_local_index_enabled = _validate_optional_bool(path, "search_local_index_enabled", data.get("search_local_index_enabled"))
        search_local_index_stale_hours = _validate_optional_int(path, "search_local_index_stale_hours", data.get("search_local_index_stale_hours"))
        search_local_index_prune_days = _validate_optional_int(path, "search_local_index_prune_days", data.get("search_local_index_prune_days"))
        mutations_idempotency_retention_days = _validate_optional_int(
            path,
            "mutations_idempotency_retention_days",
            data.get("mutations_idempotency_retention_days"),
        )
        phase2x_disable_mutations = _validate_optional_bool(path, "phase2x_disable_mutations", data.get("phase2x_disable_mutations"))
        if not isinstance(api_base_url, str):
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "`api_base_url` must be a string.",
                details={"path": str(path)},
            )
        settings = Settings(
            api_base_url=api_base_url,
            default_tz=default_tz,
            oauth_client_id=oauth_client_id,
            oauth_device_authorize_url=oauth_device_authorize_url,
            oauth_token_url=oauth_token_url,
            oauth_scope=oauth_scope,
            oauth_poll_interval_seconds=oauth_poll_interval_seconds,
            oauth_timeout_seconds=oauth_timeout_seconds,
            events_workers=events_workers,
            events_shutdown_timeout_sec=events_shutdown_timeout_sec,
            events_dedupe_ttl_hours=events_dedupe_ttl_hours,
            events_dlq_retention_days=events_dlq_retention_days,
            events_ingress_bind_host=events_ingress_bind_host,
            events_ingress_bind_port=events_ingress_bind_port,
            events_ingress_public_base_url=events_ingress_public_base_url,
            events_ingress_path=events_ingress_path,
            events_ingress_secret_env=events_ingress_secret_env,
            search_local_index_enabled=search_local_index_enabled,
            search_local_index_stale_hours=search_local_index_stale_hours,
            search_local_index_prune_days=search_local_index_prune_days,
            mutations_idempotency_retention_days=mutations_idempotency_retention_days,
            phase2x_disable_mutations=phase2x_disable_mutations,
        )
        _SETTINGS_CACHE = settings
        _SETTINGS_CACHE_KEY = cache_key
        return settings


def save_settings(settings: Settings) -> None:
    global _SETTINGS_CACHE, _SETTINGS_CACHE_KEY
    with _SETTINGS_CACHE_LOCK:
        cfg = config_dir()
        cfg.mkdir(parents=True, exist_ok=True)
        path = settings_path()
        payload = {"api_base_url": settings.api_base_url}
        optional = {
            "default_tz": settings.default_tz,
            "oauth_client_id": settings.oauth_client_id,
            "oauth_device_authorize_url": settings.oauth_device_authorize_url,
            "oauth_token_url": settings.oauth_token_url,
            "oauth_scope": settings.oauth_scope,
            "oauth_poll_interval_seconds": settings.oauth_poll_interval_seconds,
            "oauth_timeout_seconds": settings.oauth_timeout_seconds,
            "events_workers": settings.events_workers,
            "events_shutdown_timeout_sec": settings.events_shutdown_timeout_sec,
            "events_dedupe_ttl_hours": settings.events_dedupe_ttl_hours,
            "events_dlq_retention_days": settings.events_dlq_retention_days,
            "events_ingress_bind_host": settings.events_ingress_bind_host,
            "events_ingress_bind_port": settings.events_ingress_bind_port,
            "events_ingress_public_base_url": settings.events_ingress_public_base_url,
            "events_ingress_path": settings.events_ingress_path,
            "events_ingress_secret_env": settings.events_ingress_secret_env,
            "search_local_index_enabled": settings.search_local_index_enabled,
            "search_local_index_stale_hours": settings.search_local_index_stale_hours,
            "search_local_index_prune_days": settings.search_local_index_prune_days,
            "mutations_idempotency_retention_days": settings.mutations_idempotency_retention_days,
            "phase2x_disable_mutations": settings.phase2x_disable_mutations,
        }
        for key, value in optional.items():
            if value is not None:
                payload[key] = value
        write_json_atomic(path, payload)
        _SETTINGS_CACHE = settings
        _SETTINGS_CACHE_KEY = _settings_cache_key(path)
