import json

from webex_cli.errors import CliError, DomainCode
from webex_cli.output.human import emit_error_human
from webex_cli.output.json_renderer import emit_error_json
from webex_cli.utils.redaction import redact_string, redact_value


def test_redact_string_hides_bearer_and_long_tokens() -> None:
    text = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456 and token abcdefghijklmnopqrstuvwxyz123456"
    redacted = redact_string(text)
    assert "Bearer [REDACTED]" in redacted
    assert "abcdefghijklmnopqrstuvwxyz123456" not in redacted


def test_redact_value_hides_sensitive_mapping_fields() -> None:
    payload = {"access_token": "abc1234567890abcdef1234567890", "nested": {"refresh_token": "zzz"}}
    redacted = redact_value(payload)
    assert redacted["access_token"] == "[REDACTED]"
    assert redacted["nested"]["refresh_token"] == "[REDACTED]"


def test_emit_error_json_redacts_details(capsys) -> None:
    err = CliError(
        DomainCode.AUTH_INVALID,
        "bad token",
        details={"access_token": "secret-token-value-1234567890"},
    )
    emit_error_json("auth whoami", err, request_id="r1", duration_ms=10)
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["details"]["access_token"] == "[REDACTED]"
    assert payload["meta"]["request_id"] == "r1"
    assert payload["meta"]["duration_ms"] == 10


def test_emit_error_human_redacts_details(capsys) -> None:
    err = CliError(
        DomainCode.AUTH_INVALID,
        "bad token",
        details={"refresh_token": "secret-token-value-1234567890"},
    )
    emit_error_human(err)
    captured = capsys.readouterr()
    assert "[REDACTED]" in captured.err
    assert "secret-token-value-1234567890" not in captured.err
