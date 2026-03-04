from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
import time
from typing import Iterator
import uuid

_CURRENT_PROFILE: ContextVar[str | None] = ContextVar("webex_current_profile", default=None)
_REQUEST_ID: ContextVar[str | None] = ContextVar("webex_request_id", default=None)
_REQUEST_STARTED_MONO: ContextVar[float | None] = ContextVar("webex_request_started_mono", default=None)
_LOG_FORMAT: ContextVar[str] = ContextVar("webex_log_format", default="text")


def get_current_profile() -> str | None:
    return _CURRENT_PROFILE.get()


def set_current_profile(profile: str | None) -> Token[str | None]:
    return _CURRENT_PROFILE.set(profile)


def reset_current_profile(token: Token[str | None]) -> None:
    _CURRENT_PROFILE.reset(token)


@contextmanager
def use_profile(profile: str | None) -> Iterator[None]:
    token = set_current_profile(profile)
    try:
        yield
    finally:
        reset_current_profile(token)


def set_request_id(request_id: str | None) -> Token[str | None]:
    resolved = request_id.strip() if request_id and request_id.strip() else str(uuid.uuid4())
    return _REQUEST_ID.set(resolved)


def get_request_id() -> str:
    value = _REQUEST_ID.get()
    if value:
        return value
    generated = str(uuid.uuid4())
    _REQUEST_ID.set(generated)
    return generated


def reset_request_id(token: Token[str | None]) -> None:
    _REQUEST_ID.reset(token)


def mark_request_start() -> Token[float | None]:
    return _REQUEST_STARTED_MONO.set(time.monotonic())


def get_duration_ms() -> int | None:
    started = _REQUEST_STARTED_MONO.get()
    if started is None:
        return None
    return int((time.monotonic() - started) * 1000)


def reset_request_start(token: Token[float | None]) -> None:
    _REQUEST_STARTED_MONO.reset(token)


def set_log_format(log_format: str) -> Token[str]:
    return _LOG_FORMAT.set(log_format)


def get_log_format() -> str:
    return _LOG_FORMAT.get()


def reset_log_format(token: Token[str]) -> None:
    _LOG_FORMAT.reset(token)
