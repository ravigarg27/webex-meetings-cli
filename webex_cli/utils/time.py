from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from webex_cli.errors import CliError, DomainCode


def _parse_dt(value: str, tz_name: str | None) -> datetime:
    try:
        if "T" not in value:
            tz = ZoneInfo(tz_name) if tz_name else datetime.now().astimezone().tzinfo
            if tz is None:
                tz = timezone.utc
            return datetime.combine(datetime.fromisoformat(value).date(), time.min, tz)
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            tz = ZoneInfo(tz_name) if tz_name else datetime.now().astimezone().tzinfo
            if tz is None:
                tz = timezone.utc
            dt = dt.replace(tzinfo=tz)
        return dt
    except Exception as exc:
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            f"Invalid datetime value: {value}",
            details={"value": value},
        ) from exc


def parse_time_range(from_value: str, to_value: str, tz_name: str | None) -> tuple[str, str]:
    start = _parse_dt(from_value, tz_name).astimezone(timezone.utc)
    end = _parse_dt(to_value, tz_name).astimezone(timezone.utc)
    if start >= end:
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "`--from` must be earlier than `--to`.",
            details={"from": start.isoformat(), "to": end.isoformat()},
        )
    return start.isoformat(), end.isoformat()

