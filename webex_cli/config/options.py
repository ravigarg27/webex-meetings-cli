from __future__ import annotations

import os
from typing import Any

from webex_cli.config.profiles import ProfileStore
from webex_cli.config.settings import load_settings
from webex_cli.errors import CliError, DomainCode
from webex_cli.runtime import get_current_profile


def resolve_profile() -> str:
    explicit = get_current_profile()
    env_profile = os.environ.get("WEBEX_PROFILE")
    preferred = explicit if explicit else env_profile
    return ProfileStore().resolve(preferred=preferred)


def _coerce_bool(value: Any, env_name: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise CliError(DomainCode.VALIDATION_ERROR, f"{env_name} must be a boolean value.", details={"value": value})


def _coerce_int(value: Any, env_name: str) -> int:
    if isinstance(value, bool):
        raise CliError(DomainCode.VALIDATION_ERROR, f"{env_name} must be an integer.", details={"value": value})
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        raise CliError(DomainCode.VALIDATION_ERROR, f"{env_name} must not be empty.", details={"value": value})
    try:
        return int(text)
    except ValueError as exc:
        raise CliError(DomainCode.VALIDATION_ERROR, f"{env_name} must be an integer.", details={"value": value}) from exc


def _coerce_str(value: Any, env_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise CliError(DomainCode.VALIDATION_ERROR, f"{env_name} must not be empty.", details={"value": value})
    return text


def resolve_option(
    cli_value: Any,
    env_name: str,
    profile_key: str,
    settings_attr: str,
    *,
    default: Any,
    value_type: str,
) -> Any:
    def _coerce(value: Any) -> Any:
        if value_type == "bool":
            return _coerce_bool(value, env_name)
        if value_type == "int":
            return _coerce_int(value, env_name)
        return _coerce_str(value, env_name)

    if cli_value is not None:
        return _coerce(cli_value)

    env_value = os.environ.get(env_name)
    if env_value is not None:
        return _coerce(env_value)

    profile_name = resolve_profile()
    profile_value = ProfileStore().get_setting(profile_name, profile_key)
    if profile_value is not None:
        return _coerce(profile_value)

    global_value = getattr(load_settings(), settings_attr)
    if global_value is not None:
        return _coerce(global_value)

    return default
