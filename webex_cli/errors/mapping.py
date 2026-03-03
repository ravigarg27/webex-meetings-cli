from __future__ import annotations

from webex_cli.errors.codes import DomainCode

EXIT_CODE_MAP: dict[DomainCode, int] = {
    DomainCode.VALIDATION_ERROR: 2,
    DomainCode.AUTH_REQUIRED: 3,
    DomainCode.AUTH_INVALID: 3,
    DomainCode.NOT_FOUND: 4,
    DomainCode.NO_ACCESS: 5,
    DomainCode.RATE_LIMITED: 6,
    DomainCode.UPSTREAM_UNAVAILABLE: 6,
    DomainCode.ARTIFACT_NOT_READY: 7,
    DomainCode.OVERWRITE_CONFLICT: 8,
    DomainCode.DOWNLOAD_FAILED: 10,
    DomainCode.AMBIGUOUS_RECORDING: 2,
    DomainCode.TRANSCRIPT_DISABLED: 5,
    DomainCode.RECORDING_DISABLED: 5,
    DomainCode.INTERNAL_ERROR: 10,
}

RETRYABLE_MAP: dict[DomainCode, bool] = {
    DomainCode.VALIDATION_ERROR: False,
    DomainCode.AUTH_REQUIRED: False,
    DomainCode.AUTH_INVALID: False,
    DomainCode.NOT_FOUND: False,
    DomainCode.NO_ACCESS: False,
    DomainCode.RATE_LIMITED: True,
    DomainCode.UPSTREAM_UNAVAILABLE: True,
    DomainCode.ARTIFACT_NOT_READY: True,
    DomainCode.OVERWRITE_CONFLICT: False,
    DomainCode.DOWNLOAD_FAILED: False,
    DomainCode.AMBIGUOUS_RECORDING: False,
    DomainCode.TRANSCRIPT_DISABLED: False,
    DomainCode.RECORDING_DISABLED: False,
    DomainCode.INTERNAL_ERROR: False,
}


def exit_code_for(code: DomainCode) -> int:
    return EXIT_CODE_MAP[code]


def retryable_for(code: DomainCode) -> bool:
    return RETRYABLE_MAP[code]
