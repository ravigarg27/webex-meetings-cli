import contextvars

from webex_cli.commands.common import profile_scope
from webex_cli.runtime import (
    get_request_id,
    mark_request_start,
    peek_request_id,
    peek_request_start,
    reset_request_id,
    reset_request_start,
    set_request_id,
)


def test_profile_scope_creates_and_cleans_request_context_when_missing() -> None:
    def _scenario() -> None:
        assert peek_request_id() is None
        assert peek_request_start() is None
        with profile_scope(None):
            request_id = get_request_id()
            assert request_id
            assert peek_request_start() is not None
        assert peek_request_id() is None
        assert peek_request_start() is None

    contextvars.Context().run(_scenario)


def test_profile_scope_preserves_existing_request_context() -> None:
    def _scenario() -> None:
        request_id_token = set_request_id("seed-request-id")
        request_start_token = mark_request_start()
        try:
            with profile_scope(None):
                assert get_request_id() == "seed-request-id"
            assert peek_request_id() == "seed-request-id"
            assert peek_request_start() is not None
        finally:
            reset_request_start(request_start_token)
            reset_request_id(request_id_token)

    contextvars.Context().run(_scenario)
