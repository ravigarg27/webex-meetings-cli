from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from webex_cli.errors import CliError, DomainCode

INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')


def sanitize_filename(value: str) -> str:
    clean = INVALID_CHARS.sub("_", value)
    clean = clean.strip().strip(".")
    return clean or "artifact"


def atomic_write_bytes(path: Path, data: bytes, overwrite: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise CliError(
            DomainCode.OVERWRITE_CONFLICT,
            "Output file exists. Use --overwrite to replace it.",
            details={"path": str(path)},
        )
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        Path(tmp_path).replace(path)
    finally:
        tmp = Path(tmp_path)
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str, overwrite: bool = False) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), overwrite=overwrite)
