from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import time
from typing import Any, Callable

from webex_cli.config.paths import capabilities_cache_path, config_dir
from webex_cli.errors import CliError, DomainCode
from webex_cli.utils.files import write_json_atomic


@dataclass(frozen=True)
class CapabilityResult:
    available: bool
    checked_at: float
    reason_code: str | None = None
    details: dict[str, Any] | None = None


def capability_unavailable(error_code: str, message: str, *, details: dict[str, Any] | None = None) -> CliError:
    return CliError(DomainCode.CAPABILITY_ERROR, message, details=details or {}, error_code=error_code)


def _load_cache() -> dict[str, Any]:
    path = capabilities_cache_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_cache(payload: dict[str, Any]) -> None:
    cfg = config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    write_json_atomic(capabilities_cache_path(), payload)


def _normalize_result(result: CapabilityResult | bool) -> CapabilityResult:
    if isinstance(result, CapabilityResult):
        return result
    return CapabilityResult(available=bool(result), checked_at=time.time(), reason_code=None, details={})


def probe_capability(
    name: str,
    *,
    profile: str,
    probe_fn: Callable[[], CapabilityResult | bool],
    ttl_seconds: int = 900,
    refresh: bool = False,
) -> CapabilityResult:
    cache = _load_cache()
    profile_cache = cache.get(profile)
    if not isinstance(profile_cache, dict):
        profile_cache = {}

    if not refresh:
        entry = profile_cache.get(name)
        if isinstance(entry, dict):
            checked_at = entry.get("checked_at")
            if isinstance(checked_at, (int, float)) and (time.time() - float(checked_at)) < ttl_seconds:
                return CapabilityResult(
                    available=bool(entry.get("available")),
                    checked_at=float(checked_at),
                    reason_code=str(entry.get("reason_code")) if entry.get("reason_code") else None,
                    details=entry.get("details") if isinstance(entry.get("details"), dict) else {},
                )

    result = _normalize_result(probe_fn())
    profile_cache[name] = asdict(result)
    cache[profile] = profile_cache
    _save_cache(cache)
    return result
