from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfoNotFoundError
from zoneinfo import ZoneInfo

from webex_cli.errors import CliError, DomainCode


def _parse_dt(value: str, tz_name: str | None) -> datetime:
    try:
        if tz_name:
            try:
                tz_candidate = ZoneInfo(tz_name)
            except ZoneInfoNotFoundError as exc:
                raise CliError(
                    DomainCode.VALIDATION_ERROR,
                    f"Invalid timezone: {tz_name}",
                    details={"timezone": tz_name},
                ) from exc
        else:
            tz_candidate = datetime.now().astimezone().tzinfo or timezone.utc

        if "T" not in value:
            return datetime.combine(datetime.fromisoformat(value).date(), time.min, tz_candidate)
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz_candidate)
        return dt
    except CliError:
        raise
    except Exception as exc:
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            f"Invalid datetime value: {value}",
            details={"value": value},
        ) from exc


def _utc_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time_range(from_value: str, to_value: str, tz_name: str | None) -> tuple[str, str]:
    start = _parse_dt(from_value, tz_name).astimezone(timezone.utc)
    end = _parse_dt(to_value, tz_name).astimezone(timezone.utc)
    if start >= end:
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "`--from` must be earlier than `--to`.",
            details={"from": _utc_iso(start), "to": _utc_iso(end)},
        )
    return _utc_iso(start), _utc_iso(end)
