import pytest

from webex_cli.errors import CliError, DomainCode
from webex_cli.utils.time import parse_time_range


def test_parse_time_range_date_values() -> None:
    start, end = parse_time_range("2026-01-01", "2026-01-02", "UTC")
    assert start.startswith("2026-01-01T00:00:00")
    assert end.startswith("2026-01-02T00:00:00")


def test_parse_time_range_rejects_reverse_range() -> None:
    with pytest.raises(CliError) as exc:
        parse_time_range("2026-01-02", "2026-01-01", "UTC")
    assert exc.value.code == DomainCode.VALIDATION_ERROR


def test_parse_time_range_rejects_invalid_timezone() -> None:
    with pytest.raises(CliError) as exc:
        parse_time_range("2026-01-01", "2026-01-02", "Not/AZone")
    assert exc.value.code == DomainCode.VALIDATION_ERROR
    assert "Invalid timezone" in exc.value.message
