from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable
import uuid

from webex_cli.config.options import resolve_option
from webex_cli.config.paths import config_dir, mutation_idempotency_cache_path
from webex_cli.errors import CliError, DomainCode
from webex_cli.runtime import get_non_interactive
from webex_cli.utils.files import write_json_atomic

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


@dataclass(frozen=True)
class MutationResponse:
    payload: dict[str, Any]
    warnings: list[str]


def _cache_path(profile: str) -> Path:
    return mutation_idempotency_cache_path(profile)


def _load_cache(profile: str) -> dict[str, Any]:
    path = _cache_path(profile)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_cache(profile: str, payload: dict[str, Any]) -> None:
    cfg = config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    path = _cache_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, payload)


def cleanup_idempotency_cache(profile: str) -> None:
    retention_days = resolve_option(
        None,
        "WEBEX_MUTATIONS_IDEMPOTENCY_RETENTION_DAYS",
        "mutations.idempotency_retention_days",
        "mutations_idempotency_retention_days",
        default=7,
        value_type="int",
    )
    payload = _load_cache(profile)
    if not payload:
        return
    horizon_seconds = float(retention_days) * 86400.0
    kept: dict[str, Any] = {}
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        created_at = value.get("created_at")
        if not isinstance(created_at, (int, float)):
            continue
        import time

        if (time.time() - float(created_at)) <= horizon_seconds:
            kept[key] = value
    if kept != payload:
        _write_cache(profile, kept)


def ensure_mutations_enabled() -> None:
    disabled = resolve_option(
        None,
        "WEBEX_PHASE2X_DISABLE_MUTATIONS",
        "mutations.disable",
        "phase2x_disable_mutations",
        default=False,
        value_type="bool",
    )
    if disabled:
        raise CliError(
            DomainCode.STATE_ERROR,
            "Mutations are disabled by runtime policy.",
            error_code="MUTATIONS_DISABLED",
        )


def require_confirmation(confirm: bool, yes: bool, *, command_label: str) -> None:
    if confirm or yes:
        return
    if get_non_interactive():
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            f"{command_label} requires --confirm or --yes in non-interactive mode.",
            error_code="CONFIRMATION_REQUIRED_NON_INTERACTIVE",
        )


def resolve_idempotency_key(provided_key: str | None, auto: bool) -> str:
    if isinstance(provided_key, str) and provided_key.strip():
        key = provided_key.strip()
        if not IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Idempotency key format is invalid.",
                details={"idempotency_key": provided_key},
            )
        return key
    if auto:
        return f"auto-{uuid.uuid4().hex}"
    raise CliError(
        DomainCode.VALIDATION_ERROR,
        "Provide --idempotency-key or use --idempotency-auto.",
    )


def _payload_digest(command: str, payload: dict[str, Any]) -> str:
    normalized = json.dumps({"command": command, "payload": payload}, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _operation_id() -> str:
    return f"op-{uuid.uuid4().hex}"


def run_mutation(
    *,
    profile: str,
    command: str,
    payload: dict[str, Any],
    dry_run: bool,
    idempotency_key: str,
    validation: dict[str, Any] | None,
    execute: Callable[[str], dict[str, Any]],
) -> MutationResponse:
    import time

    ensure_mutations_enabled()
    cleanup_idempotency_cache(profile)

    validation_payload = validation or {}
    if dry_run:
        return MutationResponse(
            payload={
                "operation_id": _operation_id(),
                "idempotency_key": idempotency_key,
                "state": "dry_run_validated",
                "dry_run": True,
                "dry_run_mode": "local_validation",
                "validation": validation_payload,
                "warnings": [],
            },
            warnings=[],
        )

    digest = _payload_digest(command, payload)
    cache = _load_cache(profile)
    existing = cache.get(idempotency_key)
    if isinstance(existing, dict):
        if existing.get("digest") != digest:
            raise CliError(
                DomainCode.CONFLICT_ERROR,
                "Idempotency key was already used for a different mutation payload.",
                details={"idempotency_key": idempotency_key},
                error_code="MUTATION_CONFLICT",
            )
        stored_response = existing.get("response")
        if isinstance(stored_response, dict):
            response = dict(stored_response)
            response["state"] = "no_op"
            return MutationResponse(payload=response, warnings=[])

    result = execute(idempotency_key)
    response = {
        "operation_id": _operation_id(),
        "idempotency_key": idempotency_key,
        "state": "completed",
        "dry_run": False,
        "dry_run_mode": "none",
        "validation": validation_payload,
        "warnings": [],
    }
    if isinstance(result, dict):
        response.update(result)

    cache[idempotency_key] = {
        "command": command,
        "digest": digest,
        "created_at": time.time(),
        "response": response,
    }
    _write_cache(profile, cache)
    return MutationResponse(payload=response, warnings=[])
