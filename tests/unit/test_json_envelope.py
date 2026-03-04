import json

from webex_cli.errors import CliError, DomainCode
from webex_cli.output.json_renderer import emit_error_json, emit_success_json


def test_emit_success_json_shape(capsys) -> None:
    emit_success_json("meeting list", {"items": []}, warnings=["MAX_ITEMS_GUARD_HIT"], request_id="req-1", duration_ms=5)
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["command"] == "meeting list"
    assert payload["data"] == {"items": []}
    assert payload["warnings"] == ["MAX_ITEMS_GUARD_HIT"]
    assert payload["error"] is None
    assert "cli_version" in payload["meta"]
    assert "schema_version" in payload["meta"]
    assert payload["meta"]["request_id"] == "req-1"
    assert payload["meta"]["duration_ms"] == 5


def test_emit_error_json_shape(capsys) -> None:
    err = CliError(DomainCode.NO_ACCESS, "Forbidden")
    emit_error_json("recording download", err)
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["command"] == "recording download"
    assert payload["error"]["code"] == "NO_ACCESS"
    assert payload["error"]["retryable"] is False
