from __future__ import annotations

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import typer

from webex_cli.capabilities import capability_unavailable
from webex_cli.commands.common import build_client, emit_success, fail, handle_unexpected, managed_client, profile_scope, resolve_profile
from webex_cli.config.options import resolve_option
from webex_cli.errors import CliError, DomainCode
from webex_cli.eventing import EventStore, validate_webhook_signature
from webex_cli.mutations import require_confirmation
from webex_cli.utils.redaction import redact_value

event_app = typer.Typer(help="Consume and manage Webex event streams.")
ingress_app = typer.Typer(help="Run local Webex webhook ingress.")
dlq_app = typer.Typer(help="Inspect and replay dead-lettered events.")
checkpoint_app = typer.Typer(help="Inspect and manage event checkpoints.")
_MAX_EVENT_DELIVERY_ATTEMPTS = 3


def _store_for_active_profile() -> EventStore:
    return EventStore(resolve_profile())


def _normalize_public_url(public_base_url: str) -> str:
    parsed = urlparse(public_base_url.strip())
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "Ingress public base URL must be a valid https URL.",
            details={"public_base_url": public_base_url},
        )
    if parsed.query or parsed.fragment:
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            "Ingress public base URL must not include query parameters or fragments.",
            details={"public_base_url": public_base_url},
        )
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _normalize_path(path: str) -> str:
    candidate = path.strip()
    if not candidate:
        raise CliError(DomainCode.VALIDATION_ERROR, "Ingress path must not be empty.")
    if not candidate.startswith("/"):
        candidate = f"/{candidate}"
    return "/" if candidate == "/" else candidate.rstrip("/")


def _render_event(event: dict[str, Any], payload_mode: str) -> dict[str, Any]:
    correlation_id = None
    headers = event.get("headers")
    if isinstance(headers, dict):
        for key, value in headers.items():
            if str(key).lower() in {"x-request-id", "x-correlation-id"}:
                correlation_id = str(value)
                break
    rendered = {
        "seq": event.get("seq"),
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "occurred_at": event.get("occurred_at"),
        "resource_id": event.get("resource_id"),
        "correlation_id": correlation_id,
        "source": event.get("source"),
        "source_record": event.get("source_record"),
        "delivery_attempt": event.get("delivery_attempt"),
    }
    if payload_mode == "full":
        rendered["payload"] = event.get("payload")
    elif payload_mode == "redacted":
        rendered["payload"] = redact_value(event.get("payload"))
    return rendered


def _write_sink(item: dict[str, Any], sink: str, sink_path: str | None) -> None:
    if sink == "stdout":
        typer.echo(json.dumps(item, default=str))
        return
    if sink in {"file", "jsonl"}:
        if not sink_path:
            raise CliError(DomainCode.VALIDATION_ERROR, "`--sink-path` is required when sink is file/jsonl.")
        path = Path(sink_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(item, default=str))
            handle.write("\n")
        return
    raise CliError(DomainCode.VALIDATION_ERROR, "Unsupported sink.", details={"sink": sink})


def enqueue_webhook_event(
    *,
    payload: dict[str, Any],
    headers: dict[str, Any],
    validate_signature: bool,
    secret: str | None = None,
) -> dict[str, Any] | None:
    if validate_signature:
        resolved_secret = secret
        if not resolved_secret:
            env_name = resolve_option(
                None,
                "WEBEX_EVENTS_INGRESS_SECRET_ENV",
                "events.ingress_secret_env",
                "events_ingress_secret_env",
                default="WEBEX_WEBHOOK_SECRET",
                value_type="str",
            )
            resolved_secret = os.environ.get(env_name)
        if not resolved_secret:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Webhook signature validation requested but no secret is configured.",
                error_code="EVENT_SECRET_MISSING",
            )
        validate_webhook_signature(
            json.dumps(payload, sort_keys=True).encode("utf-8"),
            headers,
            resolved_secret,
        )
    return _store_for_active_profile().append_event(payload, headers=headers, source="webex-webhook")


def _run_ingress_server(
    *,
    bind_host: str,
    bind_port: int,
    public_base_url: str,
    path: str,
    secret_env: str,
    startup_result: dict[str, Any] | None = None,
    on_started: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    store = _store_for_active_profile()

    class _IngressHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != path:
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"ok":false,"error":"invalid_json"}')
                return
            secret = os.environ.get(secret_env)
            if secret:
                try:
                    validate_webhook_signature(raw, dict(self.headers.items()), secret)
                except CliError:
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'{"ok":false,"error":"invalid_signature"}')
                    return
            store.append_event(payload, headers=dict(self.headers.items()), source="webex-webhook")
            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true,"accepted":true}')

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    server = ThreadingHTTPServer((bind_host, bind_port), _IngressHandler)
    result = {
        "accepted": True,
        "bind_host": bind_host,
        "bind_port": bind_port,
        "public_base_url": public_base_url,
        "path": path,
        "secret_env": secret_env,
    }
    if startup_result:
        result.update(startup_result)
    if on_started is not None:
        on_started(result)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return None


def _normalize_event_for_file(payload: dict[str, Any], record_number: int) -> dict[str, Any]:
    return {
        "seq": record_number,
        "event_id": str(payload.get("id") or payload.get("eventId") or f"file-{record_number}"),
        "event_type": str(payload.get("event") or payload.get("eventType") or "unknown"),
        "occurred_at": str(payload.get("created") or datetime.now(timezone.utc).isoformat()),
        "resource_id": str((payload.get("data") or {}).get("id") or payload.get("resourceId") or ""),
        "payload": payload,
        "headers": {},
        "source": "file",
        "source_record": record_number,
        "delivery_attempt": 1,
    }


def _confirm_or_prompt(command_label: str, confirm: bool) -> None:
    require_confirmation(confirm, False, command_label=command_label)
    if confirm:
        return
    if not typer.confirm(f"Proceed with {command_label}?"):
        raise CliError(DomainCode.VALIDATION_ERROR, "Operation cancelled by user.")


def _dispatch_webhook_event(
    *,
    store: EventStore,
    event: dict[str, Any],
    checkpoint: str,
    payload_mode: str,
    sink: str,
    sink_path: str | None,
) -> dict[str, Any] | None:
    rendered = _render_event(event, payload_mode)
    try:
        _write_sink(rendered, sink, sink_path)
    except CliError as exc:
        attempt = int(event.get("delivery_attempt") or 1)
        if exc.retryable and attempt < _MAX_EVENT_DELIVERY_ATTEMPTS:
            store.append_event(
                event["payload"],
                headers=event.get("headers") or {},
                source=str(event.get("source") or "webex-webhook"),
                delivery_attempt=attempt + 1,
                force=True,
            )
            store.commit_checkpoint(checkpoint, "webex-webhook", str(event["seq"]))
            return None
        store.write_dlq(event, error_code=exc.error_code or exc.code.value, error_message=exc.message)
        store.commit_checkpoint(checkpoint, "webex-webhook", str(event["seq"]))
        return None
    except Exception as exc:
        store.write_dlq(event, error_code="EVENT_RETRY_EXHAUSTED", error_message=str(exc))
        store.commit_checkpoint(checkpoint, "webex-webhook", str(event["seq"]))
        return None
    store.commit_checkpoint(checkpoint, "webex-webhook", str(event["seq"]))
    return rendered


def _desired_webhooks(profile: str, *, public_base_url: str, path: str, secret: str | None) -> list[dict[str, Any]]:
    target_url = f"{public_base_url}{path}"
    resources = ("meetings", "recordings", "meetingTranscripts")
    payloads: list[dict[str, Any]] = []
    for resource in resources:
        payloads.append(
            {
                "name": f"webex-cli:{profile}:{resource}",
                "targetUrl": target_url,
                "resource": resource,
                "event": "all",
                "secret": secret or "",
            }
        )
    return payloads


def _register_webhooks(*, profile: str, public_base_url: str, path: str, secret_env: str) -> dict[str, Any]:
    secret = os.environ.get(secret_env)
    desired = _desired_webhooks(profile, public_base_url=public_base_url, path=path, secret=secret)
    try:
        with managed_client(client_factory=build_client) as client:
            list_method = getattr(client, "list_webhooks", None)
            create_method = getattr(client, "create_webhook", None)
            update_method = getattr(client, "update_webhook", None)
            if not callable(list_method) or not callable(create_method) or not callable(update_method):
                raise capability_unavailable(
                    "EVENT_INGRESS_CAPABILITY_UNAVAILABLE",
                    "Webhook auto-registration is unavailable in this build.",
                    details={"fallback_command": "webex event ingress run --register=false"},
                )
            existing_items = list_method()
            if not isinstance(existing_items, list):
                existing_items = []
            existing_by_name = {
                str(item.get("name")): item
                for item in existing_items
                if isinstance(item, dict) and item.get("name")
            }
            created: list[dict[str, Any]] = []
            updated: list[dict[str, Any]] = []
            unchanged: list[dict[str, Any]] = []
            for payload in desired:
                current = existing_by_name.get(payload["name"])
                if current is None:
                    created.append(create_method(payload))
                    continue
                comparable = {
                    "targetUrl": current.get("targetUrl"),
                    "resource": current.get("resource"),
                    "event": current.get("event"),
                    "secret": current.get("secret") or "",
                }
                if comparable == {k: payload[k] for k in comparable}:
                    unchanged.append(current)
                    continue
                updated.append(update_method(str(current.get("id")), payload))
    except CliError as exc:
        if exc.code in {DomainCode.NO_ACCESS, DomainCode.NOT_FOUND, DomainCode.CAPABILITY_ERROR, DomainCode.VALIDATION_ERROR}:
            raise capability_unavailable(
                "EVENT_INGRESS_CAPABILITY_UNAVAILABLE",
                "Webhook auto-registration is unavailable for this profile or upstream capability set.",
                details={"fallback_command": "webex event ingress run --register=false"},
            ) from exc
        raise
    return {
        "target_url": f"{public_base_url}{path}",
        "created": len(created),
        "updated": len(updated),
        "unchanged": len(unchanged),
        "items": created + updated + unchanged,
    }


@ingress_app.command("run", help="Run local webhook ingress for Webex events.")
def run_ingress(
    bind_host: str = typer.Option("127.0.0.1", "--bind-host", help="Local interface to bind."),
    bind_port: int = typer.Option(8787, "--bind-port", help="Local port to bind."),
    public_base_url: str | None = typer.Option(None, "--public-base-url", help="Public https base URL for webhook callbacks."),
    path: str | None = typer.Option(None, "--path", help="Webhook path to accept."),
    secret_env: str | None = typer.Option(None, "--secret-env", help="Environment variable that holds the webhook secret."),
    register: bool = typer.Option(False, "--register", help="Register the webhook upstream after validation."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "event ingress run"
    try:
        with profile_scope(None):
            resolved_public_base_url = _normalize_public_url(
                resolve_option(
                    public_base_url,
                    "WEBEX_EVENTS_INGRESS_PUBLIC_BASE_URL",
                    "events.ingress_public_base_url",
                    "events_ingress_public_base_url",
                    default="https://127.0.0.1.invalid",
                    value_type="str",
                )
            )
            resolved_path = _normalize_path(
                resolve_option(
                    path,
                    "WEBEX_EVENTS_INGRESS_PATH",
                    "events.ingress_path",
                    "events_ingress_path",
                    default="/webhooks/webex",
                    value_type="str",
                )
            )
            resolved_secret_env = resolve_option(
                secret_env,
                "WEBEX_EVENTS_INGRESS_SECRET_ENV",
                "events.ingress_secret_env",
                "events_ingress_secret_env",
                default="WEBEX_WEBHOOK_SECRET",
                value_type="str",
            )
            result: dict[str, Any] = {
                "accepted": True,
                "bind_host": bind_host,
                "bind_port": bind_port,
                "public_base_url": resolved_public_base_url,
                "path": resolved_path,
                "secret_env": resolved_secret_env,
            }
            if register:
                result["registration"] = _register_webhooks(
                    profile=resolve_profile(),
                    public_base_url=resolved_public_base_url,
                    path=resolved_path,
                    secret_env=resolved_secret_env,
                )
            final_result = _run_ingress_server(
                bind_host=bind_host,
                bind_port=bind_port,
                public_base_url=resolved_public_base_url,
                path=resolved_path,
                secret_env=resolved_secret_env,
                startup_result=result,
                on_started=lambda payload: emit_success(command, payload, as_json=json_output),
            )
            if isinstance(final_result, dict):
                emitted_result = final_result.get("startup_result") if isinstance(final_result.get("startup_result"), dict) else final_result
                emit_success(command, emitted_result, as_json=json_output)
    except CliError as exc:
        fail(command, exc, json_output)
    except Exception as exc:  # pragma: no cover
        handle_unexpected(command, json_output, exc)


@ingress_app.command("status", help="Show local ingress configuration state.")
def ingress_status(
    checkpoint: str = typer.Option("default", "--checkpoint", help="Checkpoint name to inspect."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "event ingress status"
    try:
        with profile_scope(None):
            emit_success(command, _store_for_active_profile().status(checkpoint), as_json=json_output)
    except CliError as exc:
        fail(command, exc, json_output)
    except Exception as exc:  # pragma: no cover
        handle_unexpected(command, json_output, exc)


@event_app.command("listen", help="Consume events from file input or the local webhook queue.")
def listen(
    source: str = typer.Option(..., "--source", help="Event source: file or webex-webhook."),
    source_path: str | None = typer.Option(None, "--source-path", help="JSONL file to read when source=file."),
    from_value: str | None = typer.Option(None, "--from", help="Resume from a source-specific offset."),
    checkpoint: str = typer.Option("default", "--checkpoint", help="Checkpoint name for persisted progress."),
    max_events: int = typer.Option(100, "--max-events", help="Maximum number of events to consume."),
    workers: int | None = typer.Option(None, "--workers", help="Maximum event batch worker count."),
    shutdown_timeout_sec: int | None = typer.Option(None, "--shutdown-timeout-sec", help="Graceful shutdown timeout."),
    payload_mode: str = typer.Option("full", "--payload-mode", help="Payload mode: full, redacted, or none."),
    sink: str = typer.Option("stdout", "--sink", help="Output sink: stdout, file, or jsonl."),
    sink_path: str | None = typer.Option(None, "--sink-path", help="Output file for file/jsonl sinks."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "event listen"
    try:
        with profile_scope(None):
            normalized_source = source.strip().lower()
            if normalized_source not in {"file", "webex-webhook"}:
                raise CliError(DomainCode.VALIDATION_ERROR, "Unsupported event source.", details={"source": source})
            if payload_mode not in {"full", "redacted", "none"}:
                raise CliError(DomainCode.VALIDATION_ERROR, "Unsupported payload mode.", details={"payload_mode": payload_mode})
            resolved_workers = resolve_option(
                workers,
                "WEBEX_EVENTS_WORKERS",
                "events.workers",
                "events_workers",
                default=1,
                value_type="int",
            )
            if resolved_workers < 1:
                raise CliError(DomainCode.VALIDATION_ERROR, "`--workers` must be at least 1.")
            resolved_shutdown_timeout = resolve_option(
                shutdown_timeout_sec,
                "WEBEX_EVENTS_SHUTDOWN_TIMEOUT_SEC",
                "events.shutdown_timeout_sec",
                "events_shutdown_timeout_sec",
                default=5,
                value_type="int",
            )
            if resolved_shutdown_timeout < 1:
                raise CliError(DomainCode.VALIDATION_ERROR, "`--shutdown-timeout-sec` must be at least 1.")
            if max_events < 1:
                raise CliError(DomainCode.VALIDATION_ERROR, "`--max-events` must be at least 1.")

            store = _store_for_active_profile()
            rendered_items: list[dict[str, Any]] = []
            processed = 0

            if normalized_source == "file":
                if not source_path:
                    raise CliError(DomainCode.VALIDATION_ERROR, "`--source-path` is required for source=file.")
                start_record = int(from_value or store.get_checkpoint(checkpoint, "file") or 0)
                source_file = Path(source_path)
                if not source_file.exists():
                    raise CliError(DomainCode.NOT_FOUND, "Event source file was not found.", details={"source_path": source_path})
                with source_file.open("r", encoding="utf-8") as handle:
                    for record_number, raw_line in enumerate(handle, start=1):
                        if record_number <= start_record:
                            continue
                        line = raw_line.strip()
                        if not line:
                            continue
                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise CliError(
                                DomainCode.VALIDATION_ERROR,
                                "Event source file contains invalid JSON.",
                                details={"source_path": source_path, "line": record_number},
                            ) from exc
                        event = _normalize_event_for_file(payload, record_number)
                        rendered = _render_event(event, payload_mode)
                        try:
                            _write_sink(rendered, sink, sink_path)
                        except Exception as sink_exc:
                            store.write_dlq(event, error_code="EVENT_RETRY_EXHAUSTED", error_message=str(sink_exc))
                            raise
                        rendered_items.append(rendered)
                        processed += 1
                        store.commit_checkpoint(checkpoint, "file", str(record_number))
                        if processed >= max_events:
                            break
            else:
                while processed < max_events:
                    items = store.queue_events(
                        checkpoint=checkpoint,
                        source="webex-webhook",
                        limit=max(1, min(max_events - processed, resolved_workers)),
                    )
                    if not items:
                        break
                    for event in items:
                        rendered = _dispatch_webhook_event(
                            store=store,
                            event=event,
                            checkpoint=checkpoint,
                            payload_mode=payload_mode,
                            sink=sink,
                            sink_path=sink_path,
                        )
                        if rendered is None:
                            continue
                        rendered_items.append(rendered)
                        processed += 1
                        if processed >= max_events:
                            break

            emit_success(
                command,
                {
                    "processed": processed,
                    "checkpoint": checkpoint,
                    "workers": resolved_workers,
                    "shutdown_timeout_sec": resolved_shutdown_timeout,
                    "items": rendered_items,
                    "next_page_token": None,
                },
                as_json=json_output,
            )
    except CliError as exc:
        fail(command, exc, json_output)
    except Exception as exc:  # pragma: no cover
        handle_unexpected(command, json_output, exc)


@event_app.command("status", help="Show queue, DLQ, and checkpoint state.")
def status(
    checkpoint: str = typer.Option("default", "--checkpoint", help="Checkpoint name to inspect."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "event status"
    try:
        with profile_scope(None):
            emit_success(command, _store_for_active_profile().status(checkpoint), as_json=json_output)
    except CliError as exc:
        fail(command, exc, json_output)
    except Exception as exc:  # pragma: no cover
        handle_unexpected(command, json_output, exc)


@dlq_app.command("replay", help="Replay events from the DLQ back into the local queue.")
def replay_events(
    from_dlq: bool = typer.Option(True, "--from-dlq/--from-queue", help="Replay from the DLQ."),
    limit: int = typer.Option(100, "--limit", help="Maximum number of DLQ entries to replay."),
    checkpoint: str = typer.Option("default", "--checkpoint", help="Checkpoint name for follow-up inspection."),
    force_replay: bool = typer.Option(False, "--force-replay", help="Replay even if the event was seen before."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "event replay"
    try:
        with profile_scope(None):
            if not from_dlq:
                raise CliError(DomainCode.VALIDATION_ERROR, "Only DLQ replay is supported right now.")
            if limit < 1:
                raise CliError(DomainCode.VALIDATION_ERROR, "`--limit` must be at least 1.")
            store = _store_for_active_profile()
            replayed = store.replay_dlq(limit=limit, force_replay=force_replay)
            emit_success(
                command,
                {
                    "replayed": replayed,
                    "checkpoint": checkpoint,
                    "status": store.status(checkpoint),
                },
                as_json=json_output,
            )
    except CliError as exc:
        fail(command, exc, json_output)
    except Exception as exc:  # pragma: no cover
        handle_unexpected(command, json_output, exc)


@event_app.command("replay", help="Replay DLQ events back into the local queue.")
def replay_root(
    from_dlq: bool = typer.Option(True, "--from-dlq/--from-queue", help="Replay from the DLQ."),
    limit: int = typer.Option(100, "--limit", help="Maximum number of DLQ entries to replay."),
    checkpoint: str = typer.Option("default", "--checkpoint", help="Checkpoint name for follow-up inspection."),
    force_replay: bool = typer.Option(False, "--force-replay", help="Replay even if the event was seen before."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    replay_events(
        from_dlq=from_dlq,
        limit=limit,
        checkpoint=checkpoint,
        force_replay=force_replay,
        json_output=json_output,
    )


@dlq_app.command("list", help="List DLQ entries.")
def list_dlq(
    limit: int = typer.Option(100, "--limit", help="Maximum number of DLQ entries to list."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "event dlq list"
    try:
        with profile_scope(None):
            if limit < 1:
                raise CliError(DomainCode.VALIDATION_ERROR, "`--limit` must be at least 1.")
            emit_success(command, {"items": _store_for_active_profile().list_dlq(limit)}, as_json=json_output)
    except CliError as exc:
        fail(command, exc, json_output)
    except Exception as exc:  # pragma: no cover
        handle_unexpected(command, json_output, exc)


@dlq_app.command("purge", help="Purge DLQ entries.")
def purge_dlq(
    older_than: str | None = typer.Option(None, "--older-than", help="Delete entries older than the given ISO timestamp."),
    confirm: bool = typer.Option(False, "--confirm", help="Confirm the purge without prompting."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "event dlq purge"
    try:
        with profile_scope(None):
            _confirm_or_prompt("event dlq purge", confirm)
            purged = _store_for_active_profile().purge_dlq(older_than)
            emit_success(command, {"purged": purged}, as_json=json_output)
    except CliError as exc:
        fail(command, exc, json_output)
    except Exception as exc:  # pragma: no cover
        handle_unexpected(command, json_output, exc)


@checkpoint_app.command("reset", help="Reset a persisted checkpoint.")
def reset_checkpoint(
    checkpoint: str = typer.Option(..., "--checkpoint", help="Checkpoint name to reset."),
    confirm: bool = typer.Option(False, "--confirm", help="Confirm the reset without prompting."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "event checkpoint reset"
    try:
        with profile_scope(None):
            _confirm_or_prompt("event checkpoint reset", confirm)
            removed = _store_for_active_profile().reset_checkpoint(checkpoint)
            emit_success(command, {"checkpoint": checkpoint, "removed": removed}, as_json=json_output)
    except CliError as exc:
        fail(command, exc, json_output)
    except Exception as exc:  # pragma: no cover
        handle_unexpected(command, json_output, exc)


event_app.add_typer(ingress_app, name="ingress")
event_app.add_typer(dlq_app, name="dlq")
event_app.add_typer(checkpoint_app, name="checkpoint")
