import pytest

from webex_cli.commands.common import fetch_all_pages
from webex_cli.errors import CliError, DomainCode


def test_fetch_all_pages_adds_warning_at_exact_cap() -> None:
    def fetch_page(token):
        if token is None:
            return ([{"id": 1}, {"id": 2}], None)
        return ([], None)

    items, warnings = fetch_all_pages(fetch_page, max_items=2)
    assert len(items) == 2
    assert warnings == ["MAX_ITEMS_GUARD_HIT"]


def test_fetch_all_pages_raises_when_cap_exceeded() -> None:
    def fetch_page(token):
        if token is None:
            return ([{"id": 1}, {"id": 2}], "n1")
        return ([{"id": 3}], None)

    with pytest.raises(CliError) as exc:
        fetch_all_pages(fetch_page, max_items=2)
    assert exc.value.code == DomainCode.RESULT_SET_TOO_LARGE
    assert "MAX_ITEMS_GUARD_HIT" in exc.value.details.get("warnings", [])
    assert exc.value.details.get("resume_page_token") == "n1"
