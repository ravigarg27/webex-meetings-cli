import pytest

from webex_cli.errors import CliError, DomainCode
from webex_cli.search import collect_pages, evaluate_filter, sort_items


def test_evaluate_filter_is_case_insensitive_by_default() -> None:
    item = {"title": "Alpha Review"}
    schema = {"title": "string"}
    assert evaluate_filter("title='alpha review'", item, schema) is True


def test_evaluate_filter_honors_case_sensitive_flag() -> None:
    item = {"title": "Alpha Review"}
    schema = {"title": "string"}
    assert evaluate_filter("title='alpha review'", item, schema, case_sensitive=True) is False


def test_evaluate_filter_honors_precedence_and_parentheses() -> None:
    schema = {"title": "string", "has_recording": "bool"}
    item = {"title": "two", "has_recording": False}
    assert evaluate_filter("title='one' OR title='two' AND has_recording=true", item, schema) is False
    assert evaluate_filter("(title='one' OR title='two') AND has_recording=false", item, schema) is True


def test_evaluate_filter_supports_datetime_comparisons() -> None:
    item = {"started_at": "2026-01-02T10:00:00Z"}
    schema = {"started_at": "datetime"}
    assert evaluate_filter("started_at>='2026-01-01T00:00:00Z'", item, schema) is True


def test_evaluate_filter_rejects_unknown_fields() -> None:
    item = {"title": "Alpha Review"}
    schema = {"title": "string"}
    with pytest.raises(CliError) as exc:
        evaluate_filter("unknown='x'", item, schema)
    assert exc.value.code == DomainCode.VALIDATION_ERROR
    assert exc.value.details["field"] == "unknown"


def test_sort_items_applies_tie_breaker() -> None:
    schema = {"started_at": "datetime", "meeting_id": "string"}
    items = [
        {"meeting_id": "m2", "started_at": "2026-01-01T10:00:00Z"},
        {"meeting_id": "m1", "started_at": "2026-01-01T10:00:00Z"},
    ]
    sorted_items = sort_items(items, "started_at:asc", schema, tie_breaker_field="meeting_id")
    assert [item["meeting_id"] for item in sorted_items] == ["m1", "m2"]


def test_collect_pages_stops_at_max_pages_with_warning() -> None:
    calls: list[str | None] = []

    def _fetch(token: str | None):
        calls.append(token)
        if token is None:
            return ([{"id": "one"}], "t1")
        if token == "t1":
            return ([{"id": "two"}], "t2")
        return ([{"id": "three"}], None)

    items, next_token, warnings = collect_pages(_fetch, start_token=None, max_pages=2)
    assert [item["id"] for item in items] == ["one", "two"]
    assert next_token == "t2"
    assert warnings == ["MAX_PAGES_LIMIT_REACHED"]
    assert calls == [None, "t1"]
