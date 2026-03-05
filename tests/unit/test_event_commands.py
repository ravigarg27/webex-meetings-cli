import json
import shutil
from pathlib import Path
import uuid

import pytest
import typer
from typer.testing import CliRunner

from webex_cli.cli import app
from webex_cli.errors import DomainCode
from webex_cli.commands import event as event_commands
from webex_cli.errors import CliError
from webex_cli.runtime import use_non_interactive


def _temp_root() -> Path:
    root = Path(".test_tmp") / f"events-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_event_ingress_run_validates_and_reports(monkeypatch, capsys) -> None:
    monkeypatch.setattr(event_commands, "_run_ingress_server", lambda **kwargs: {"accepted": True, **kwargs})
    event_commands.run_ingress(
        bind_host="127.0.0.1",
        bind_port=8080,
        public_base_url="https://example.test",
        path="/webhooks/webex",
        secret_env="WEBEX_WEBHOOK_SECRET",
        register=False,
        json_output=True,
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["accepted"] is True


def test_event_list_file_source_writes_sink_and_updates_checkpoint(monkeypatch, capsys) -> None:
    root = _temp_root()
    source_path = root / "events.jsonl"
    sink_path = root / "sink.jsonl"
    monkeypatch.setenv("APPDATA", str(root))
    source_path.write_text(
        "\n".join(
            [
                json.dumps({"id": "e1", "event": "created", "created": "2026-01-01T00:00:00Z", "data": {"id": "m1"}}),
                json.dumps({"id": "e2", "event": "updated", "created": "2026-01-01T00:01:00Z", "data": {"id": "m1"}}),
            ]
        ),
        encoding="utf-8",
    )
    try:
        event_commands.listen(
            source="file",
            source_path=str(source_path),
            from_value=None,
            checkpoint="cp1",
            max_events=10,
            workers=1,
            shutdown_timeout_sec=5,
            payload_mode="full",
            sink="file",
            sink_path=str(sink_path),
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["data"]["processed"] == 2
        lines = sink_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_event_list_file_source_invalid_json_is_validation_error(monkeypatch, capsys) -> None:
    root = _temp_root()
    source_path = root / "events.jsonl"
    sink_path = root / "sink.jsonl"
    monkeypatch.setenv("APPDATA", str(root))
    source_path.write_text('{"id":"e1"}\n{"bad"\n', encoding="utf-8")
    try:
        with pytest.raises(typer.Exit) as exc:
            event_commands.listen(
                source="file",
                source_path=str(source_path),
                from_value=None,
                checkpoint="cp-invalid",
                max_events=10,
                workers=1,
                shutdown_timeout_sec=5,
                payload_mode="full",
                sink="file",
                sink_path=str(sink_path),
                json_output=True,
            )
        payload = json.loads(capsys.readouterr().out)
        assert exc.value.exit_code == 2
        assert payload["error"]["message"] == "Event source file contains invalid JSON."
        assert payload["error"]["details"]["line"] == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_event_list_webhook_source_consumes_queue_and_persists_checkpoint(monkeypatch, capsys) -> None:
    root = _temp_root()
    sink_path = root / "sink.jsonl"
    monkeypatch.setenv("APPDATA", str(root))
    try:
        event_commands.enqueue_webhook_event(
            payload={"id": "e1", "event": "created", "created": "2026-01-01T00:00:00Z", "data": {"id": "m1"}},
            headers={},
            validate_signature=False,
        )
        event_commands.listen(
            source="webex-webhook",
            source_path=None,
            from_value=None,
            checkpoint="cp-webhook",
            max_events=10,
            workers=1,
            shutdown_timeout_sec=5,
            payload_mode="full",
            sink="file",
            sink_path=str(sink_path),
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["data"]["processed"] == 1
        status = event_commands._store_for_active_profile().status("cp-webhook")
        assert status["checkpoints"]["webex-webhook"]["value"] == "1"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_event_dlq_replay_moves_entries_back_to_queue(monkeypatch, capsys) -> None:
    root = _temp_root()
    monkeypatch.setenv("APPDATA", str(root))
    try:
        store = event_commands._store_for_active_profile()
        store.write_dlq(
            {
                "seq": 1,
                "event_id": "e-dlq",
                "event_type": "failed",
                "occurred_at": "2026-01-01T00:00:00Z",
                "resource_id": "m1",
                "payload": {"id": "m1"},
                "headers": {},
                "source": "webex-webhook",
                "delivery_attempt": 1,
            },
            error_code="EVENT_RETRY_EXHAUSTED",
            error_message="failed",
        )
        event_commands.replay_events(from_dlq=True, limit=10, checkpoint="cp1", force_replay=False, json_output=True)
        payload = json.loads(capsys.readouterr().out)
        assert payload["data"]["replayed"] == 1
        assert store.status("cp1")["queue_depth"] == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_event_checkpoint_reset_requires_confirmation_in_non_interactive(monkeypatch) -> None:
    root = _temp_root()
    monkeypatch.setenv("APPDATA", str(root))
    try:
        with use_non_interactive(True):
            with pytest.raises(typer.Exit) as exc:
                event_commands.reset_checkpoint(checkpoint="cp1", confirm=False, json_output=True)
        assert exc.value.exit_code == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_event_replay_root_command_alias(monkeypatch) -> None:
    root = _temp_root()
    monkeypatch.setenv("APPDATA", str(root))
    runner = CliRunner()
    try:
        store = event_commands._store_for_active_profile()
        store.write_dlq(
            {
                "seq": 1,
                "event_id": "e-dlq",
                "event_type": "failed",
                "occurred_at": "2026-01-01T00:00:00Z",
                "resource_id": "m1",
                "payload": {"id": "m1"},
                "headers": {},
                "source": "webex-webhook",
                "delivery_attempt": 1,
            },
            error_code="EVENT_RETRY_EXHAUSTED",
            error_message="failed",
        )
        result = runner.invoke(app, ["event", "replay", "--from-dlq", "--limit", "10", "--checkpoint", "cp1", "--json"])
        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["data"]["replayed"] == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_event_ingress_register_returns_deterministic_capability_error(monkeypatch) -> None:
    monkeypatch.setattr(event_commands, "_run_ingress_server", lambda **kwargs: {"accepted": True, **kwargs})
    monkeypatch.setattr(event_commands, "build_client", lambda token=None: object())
    with pytest.raises(typer.Exit) as exc:
        event_commands.run_ingress(
            bind_host="127.0.0.1",
            bind_port=8080,
            public_base_url="https://example.test",
            path="/webhooks/webex",
            secret_env="WEBEX_WEBHOOK_SECRET",
            register=True,
            json_output=True,
        )
    assert exc.value.exit_code == 5


class _WebhookRegistrationClient:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []

    def list_webhooks(self):
        return [
            {
                "id": "wh-meetings",
                "name": "webex-cli:default:meetings",
                "targetUrl": "https://old.example.test/webhooks/webex",
                "resource": "meetings",
                "event": "all",
                "secret": "old-secret",
                "status": "inactive",
            }
        ]

    def update_webhook(self, webhook_id: str, payload: dict):
        self.updated.append((webhook_id, payload))
        return {"id": webhook_id, **payload}

    def create_webhook(self, payload: dict):
        self.created.append(payload)
        return {"id": f"created-{payload['resource']}", **payload}


class _WebhookRegistrationForbiddenClient:
    def list_webhooks(self):
        from webex_cli.errors import CliError

        raise CliError(DomainCode.NO_ACCESS, "forbidden")


def test_event_ingress_register_creates_and_updates_expected_webhooks(monkeypatch, capsys) -> None:
    client = _WebhookRegistrationClient()
    monkeypatch.setattr(event_commands, "_run_ingress_server", lambda **kwargs: {"accepted": True, **kwargs})
    monkeypatch.setattr(event_commands, "build_client", lambda token=None: client)

    event_commands.run_ingress(
        bind_host="127.0.0.1",
        bind_port=8080,
        public_base_url="https://example.test",
        path="/webhooks/webex",
        secret_env="WEBEX_WEBHOOK_SECRET",
        register=True,
        json_output=True,
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    registration = payload["data"]["registration"]
    assert registration["updated"] == 1
    assert registration["created"] == 2
    assert {item["resource"] for item in client.created} == {"recordings", "meetingTranscripts"}
    assert client.updated[0][0] == "wh-meetings"


def test_event_ingress_run_registers_before_serving_and_emits_startup_payload(monkeypatch, capsys) -> None:
    call_order: list[str] = []

    def _register(**kwargs):
        call_order.append("register")
        return {"created": 3, "updated": 0, "unchanged": 0, "items": []}

    def _serve(**kwargs):
        call_order.append("serve")
        kwargs["on_started"](kwargs["startup_result"])
        return None

    monkeypatch.setattr(event_commands, "_register_webhooks", _register)
    monkeypatch.setattr(event_commands, "_run_ingress_server", _serve)

    event_commands.run_ingress(
        bind_host="127.0.0.1",
        bind_port=8080,
        public_base_url="https://example.test",
        path="/webhooks/webex",
        secret_env="WEBEX_WEBHOOK_SECRET",
        register=True,
        json_output=True,
    )

    payload = json.loads(capsys.readouterr().out)
    assert call_order == ["register", "serve"]
    assert payload["ok"] is True
    assert payload["data"]["registration"]["created"] == 3


def test_event_ingress_register_maps_missing_capability(monkeypatch) -> None:
    monkeypatch.setattr(event_commands, "_run_ingress_server", lambda **kwargs: {"accepted": True, **kwargs})
    monkeypatch.setattr(event_commands, "build_client", lambda token=None: _WebhookRegistrationForbiddenClient())
    with pytest.raises(typer.Exit) as exc:
        event_commands.run_ingress(
            bind_host="127.0.0.1",
            bind_port=8080,
            public_base_url="https://example.test",
            path="/webhooks/webex",
            secret_env="WEBEX_WEBHOOK_SECRET",
            register=True,
            json_output=True,
        )
    assert exc.value.exit_code == 5


def test_event_list_webhook_source_requeues_retryable_failure(monkeypatch, capsys) -> None:
    root = _temp_root()
    sink_path = root / "sink.jsonl"
    monkeypatch.setenv("APPDATA", str(root))
    attempts = {"count": 0}

    def _flaky_sink(item, sink, sink_path_value):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise CliError(DomainCode.UPSTREAM_UNAVAILABLE, "temporary", retryable=True)
        return event_commands._write_sink_original(item, sink, sink_path_value)

    try:
        event_commands.enqueue_webhook_event(
            payload={"id": "e-retry", "event": "created", "created": "2026-01-01T00:00:00Z", "data": {"id": "m1"}},
            headers={"X-Request-Id": "corr-1"},
            validate_signature=False,
        )
        monkeypatch.setattr(event_commands, "_write_sink_original", event_commands._write_sink, raising=False)
        monkeypatch.setattr(event_commands, "_write_sink", _flaky_sink)
        event_commands.listen(
            source="webex-webhook",
            source_path=None,
            from_value=None,
            checkpoint="cp-retry",
            max_events=10,
            workers=1,
            shutdown_timeout_sec=5,
            payload_mode="full",
            sink="file",
            sink_path=str(sink_path),
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["data"]["processed"] == 1
        status = event_commands._store_for_active_profile().status("cp-retry")
        assert status["checkpoints"]["webex-webhook"]["value"] == "2"
        assert status["dlq_depth"] == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_event_list_webhook_source_terminal_failure_goes_to_dlq(monkeypatch, capsys) -> None:
    root = _temp_root()
    monkeypatch.setenv("APPDATA", str(root))

    def _broken_sink(item, sink, sink_path_value):
        raise CliError(DomainCode.VALIDATION_ERROR, "bad event", retryable=False)

    try:
        event_commands.enqueue_webhook_event(
            payload={"id": "e-dead", "event": "created", "created": "2026-01-01T00:00:00Z", "data": {"id": "m1"}},
            headers={},
            validate_signature=False,
        )
        monkeypatch.setattr(event_commands, "_write_sink", _broken_sink)
        event_commands.listen(
            source="webex-webhook",
            source_path=None,
            from_value=None,
            checkpoint="cp-dlq",
            max_events=10,
            workers=1,
            shutdown_timeout_sec=5,
            payload_mode="full",
            sink="stdout",
            sink_path=None,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["data"]["processed"] == 0
        status = event_commands._store_for_active_profile().status("cp-dlq")
        assert status["checkpoints"]["webex-webhook"]["value"] == "1"
        assert status["dlq_depth"] == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)
