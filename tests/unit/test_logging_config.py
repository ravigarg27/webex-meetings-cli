import json
import logging

from webex_cli.runtime import reset_request_id, set_request_id
from webex_cli.utils.logging import configure_logging


def test_json_log_format_includes_request_id_and_redacts(capsys) -> None:
    configure_logging("json")
    token = set_request_id("req-logger-1")
    try:
        logger = logging.getLogger("webex.test")
        logger.warning("Authorization: Bearer verysecrettokenvalue1234567890")
        captured = capsys.readouterr().err.strip().splitlines()[-1]
        payload = json.loads(captured)
        assert payload["request_id"] == "req-logger-1"
        assert "verysecrettokenvalue1234567890" not in payload["message"]
    finally:
        reset_request_id(token)


def test_text_log_format_includes_request_id(capsys) -> None:
    configure_logging("text")
    token = set_request_id("req-logger-2")
    try:
        logger = logging.getLogger("webex.test")
        logger.error("hello")
        captured = capsys.readouterr().err
        assert "req-logger-2" in captured
    finally:
        reset_request_id(token)
