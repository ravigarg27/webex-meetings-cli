from __future__ import annotations

import re
from typing import Any

_SECRET_KEY_PARTS = ("token", "secret", "password", "authorization", "api_key", "apikey")

_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{8,}")
_JWT_PATTERN = re.compile(r"\b[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_TOKEN_LABEL_PATTERN = re.compile(
    r"(?i)\b(access_token|refresh_token|token|authorization)\b(\s*[:=]\s*)((?!bearer\b)[^\s,;]+)"
)


def redact_string(value: str) -> str:
    redacted = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
    redacted = _TOKEN_LABEL_PATTERN.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", redacted)
    redacted = _JWT_PATTERN.sub("[REDACTED]", redacted)
    return redacted


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SECRET_KEY_PARTS)


def redact_value(value: Any, *, key_hint: str | None = None) -> Any:
    if key_hint and _is_sensitive_key(key_hint):
        return "[REDACTED]"
    if isinstance(value, str):
        return redact_string(value)
    if isinstance(value, dict):
        return {str(k): redact_value(v, key_hint=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(item, key_hint=key_hint) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item, key_hint=key_hint) for item in value)
    return value
