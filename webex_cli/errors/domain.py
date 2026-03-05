from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from webex_cli.errors.codes import DomainCode
from webex_cli.errors.mapping import exit_code_for, retryable_for


@dataclass
class CliError(Exception):
    code: DomainCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    retryable: bool | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)
        if self.retryable is None:
            self.retryable = retryable_for(self.code)
        if self.error_code is None:
            self.error_code = self.code.value

    @property
    def exit_code(self) -> int:
        return exit_code_for(self.code)
