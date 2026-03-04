from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

_CURRENT_PROFILE: ContextVar[str | None] = ContextVar("webex_current_profile", default=None)


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

