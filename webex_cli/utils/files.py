from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from webex_cli.errors import CliError, DomainCode

INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')


def replace_file_atomic(src: Path, dest: Path, *, attempts: int = 5, base_delay_seconds: float = 0.05) -> None:
    if attempts < 1:
        attempts = 1
    for attempt in range(attempts):
        try:
            src.replace(dest)
            return
        except PermissionError:
            if os.name != "nt" or attempt == attempts - 1:
                raise
            time.sleep(base_delay_seconds * (attempt + 1))


def sanitize_filename(value: str) -> str:
    clean = INVALID_CHARS.sub("_", value)
    clean = clean.strip().strip(".")
    return clean or "artifact"


def atomic_write_stream(path: Path, chunks: Iterable[bytes], overwrite: bool = False) -> None:
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
            for chunk in chunks:
                if chunk:
                    handle.write(chunk)
        replace_file_atomic(Path(tmp_path), path)
    finally:
        tmp = Path(tmp_path)
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def atomic_write_bytes(path: Path, data: bytes, overwrite: bool = False) -> None:
    atomic_write_stream(path, [data], overwrite=overwrite)


def atomic_write_text(path: Path, text: str, overwrite: bool = False) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), overwrite=overwrite)


def write_json_atomic(path: Path, payload: dict[str, Any], *, file_mode: int = 0o600) -> None:
    text = json.dumps(payload, indent=2)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        replace_file_atomic(Path(tmp_path), path)
        if os.name != "nt":
            os.chmod(path, file_mode)
    finally:
        tmp = Path(tmp_path)
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def checksum_from_metadata(metadata: dict[str, Any]) -> tuple[str, str] | None:
    # Common key patterns observed in APIs and wrappers.
    candidates = [
        ("sha256", metadata.get("checksum_sha256")),
        ("sha256", metadata.get("sha256")),
        ("sha256", metadata.get("sha256Checksum")),
    ]
    nested = metadata.get("checksums")
    if isinstance(nested, dict):
        candidates.extend(
            [
                ("sha256", nested.get("sha256")),
            ]
        )
    for algorithm, value in candidates:
        if isinstance(value, str) and value.strip():
            return algorithm, value.strip().lower()
    return None


def compute_checksum(data: bytes, algorithm: str) -> str:
    algo = algorithm.strip().lower()
    if algo != "sha256":
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "Unsupported checksum algorithm.",
            details={"algorithm": algorithm},
        )
    digest = hashlib.new(algo)
    digest.update(data)
    return digest.hexdigest().lower()
