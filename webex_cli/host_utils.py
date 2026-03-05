from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path
import re

from webex_cli.errors import CliError, DomainCode

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SUPPORTED_RRULE_KEYS = {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY"}
SUPPORTED_FREQS = {"DAILY", "WEEKLY", "MONTHLY"}


def parse_invitees(
    *,
    invitees: str | None,
    invitees_file: str | None,
    invitees_file_format: str,
) -> list[str]:
    if bool(invitees) == bool(invitees_file):
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "Provide either inline invitees or --invitees-file.",
        )
    normalized_format = invitees_file_format.strip().lower()
    if normalized_format not in {"lines", "csv"}:
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "Invitee file format is unsupported.",
            details={"invitees_file_format": invitees_file_format},
        )
    values: list[str] = []
    if invitees:
        values = [item.strip() for item in invitees.split(",") if item.strip()]
    else:
        path = Path(str(invitees_file))
        if not path.exists():
            raise CliError(DomainCode.NOT_FOUND, "Invitees file not found.", details={"path": str(path)})
        content = path.read_text(encoding="utf-8")
        if normalized_format == "csv":
            reader = csv.DictReader(StringIO(content))
            for row in reader:
                if not isinstance(row, dict):
                    continue
                email = (row.get("email") or row.get("invitee") or row.get("attendee") or "").strip()
                if email:
                    values.append(email)
        else:
            values = [line.strip() for line in content.splitlines() if line.strip()]
    if not values:
        raise CliError(DomainCode.VALIDATION_ERROR, "No invitees were provided.")

    normalized: list[str] = []
    seen: set[str] = set()
    for email in values:
        if not EMAIL_PATTERN.fullmatch(email):
            raise CliError(DomainCode.VALIDATION_ERROR, "Invitee email is invalid.", details={"invitee": email})
        lowered = email.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(email)
    return normalized


def validate_rrule(value: str) -> str:
    parts = [part.strip() for part in value.split(";") if part.strip()]
    if not parts:
        raise CliError(DomainCode.VALIDATION_ERROR, "RRULE must not be empty.", details={"rrule": value})
    pairs: dict[str, str] = {}
    for part in parts:
        if "=" not in part:
            raise CliError(DomainCode.VALIDATION_ERROR, "RRULE segment is invalid.", details={"rrule_part": part})
        key, raw = part.split("=", 1)
        normalized_key = key.strip().upper()
        normalized_value = raw.strip().upper()
        if normalized_key not in SUPPORTED_RRULE_KEYS:
            raise CliError(DomainCode.VALIDATION_ERROR, "RRULE contains an unsupported key.", details={"rrule_key": normalized_key})
        pairs[normalized_key] = normalized_value
    if pairs.get("FREQ") not in SUPPORTED_FREQS:
        raise CliError(DomainCode.VALIDATION_ERROR, "RRULE frequency is unsupported.", details={"freq": pairs.get("FREQ")})
    ordered_keys = ["FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY"]
    return ";".join(f"{key}={pairs[key]}" for key in ordered_keys if key in pairs)
