from datetime import datetime, timedelta, timezone
import shutil
from pathlib import Path
import uuid

from webex_cli.eventing.store import EventStore


def _temp_root() -> Path:
    root = Path(".test_tmp") / f"event-store-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_event_dedupe_ttl_allows_replay_after_expiry(monkeypatch) -> None:
    root = _temp_root()
    monkeypatch.setenv("APPDATA", str(root))
    monkeypatch.setenv("WEBEX_EVENTS_DEDUPE_TTL_HOURS", "1")
    try:
        store = EventStore("default")
        first = store.append_event({"id": "evt-1", "event": "created"}, headers={}, source="webex-webhook")
        assert first is not None

        duplicate = store.append_event({"id": "evt-1", "event": "created"}, headers={}, source="webex-webhook")
        assert duplicate is None

        stale_seen_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with store._connect(store.dedupe_path) as conn:  # noqa: SLF001 - test-only introspection
            conn.execute("UPDATE dedupe SET seen_at = ? WHERE event_id = ?", (stale_seen_at, "evt-1"))
            conn.commit()

        replayed = store.append_event({"id": "evt-1", "event": "created"}, headers={}, source="webex-webhook")
        assert replayed is not None
        assert replayed["seq"] > first["seq"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_event_status_queue_depth_tracks_unprocessed_webhook_events(monkeypatch) -> None:
    root = _temp_root()
    monkeypatch.setenv("APPDATA", str(root))
    try:
        store = EventStore("default")
        first = store.append_event({"id": "evt-1", "event": "created"}, headers={}, source="webex-webhook")
        second = store.append_event({"id": "evt-2", "event": "updated"}, headers={}, source="webex-webhook")
        assert first is not None
        assert second is not None

        before = store.status("cp-status")
        assert before["queue_depth"] == 2

        store.commit_checkpoint("cp-status", "webex-webhook", str(first["seq"]))
        after = store.status("cp-status")
        assert after["queue_depth"] == 1
        assert after["checkpoints"]["webex-webhook"]["value"] == str(first["seq"])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_event_replay_dlq_skips_entries_already_replayed(monkeypatch) -> None:
    root = _temp_root()
    monkeypatch.setenv("APPDATA", str(root))
    try:
        store = EventStore("default")
        event = {
            "seq": 1,
            "event_id": "evt-dlq",
            "event_type": "created",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "resource_id": "m1",
            "payload": {"id": "evt-dlq", "event": "created"},
            "headers": {},
            "source": "webex-webhook",
            "delivery_attempt": 1,
        }
        store.write_dlq(event, error_code="EVENT_RETRY_EXHAUSTED", error_message="failed")

        first = store.replay_dlq(limit=10, force_replay=False)
        second = store.replay_dlq(limit=10, force_replay=False)

        assert first == 1
        assert second == 0
        assert store.status("default")["queue_depth"] == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_event_replay_dlq_requeues_failed_events_even_when_already_seen(monkeypatch) -> None:
    root = _temp_root()
    monkeypatch.setenv("APPDATA", str(root))
    try:
        store = EventStore("default")
        queued = store.append_event({"id": "evt-seen", "event": "created"}, headers={}, source="webex-webhook")
        assert queued is not None
        store.write_dlq(
            {
                "seq": queued["seq"],
                "event_id": queued["event_id"],
                "event_type": queued["event_type"],
                "occurred_at": queued["occurred_at"],
                "resource_id": queued["resource_id"],
                "payload": queued["payload"],
                "headers": queued["headers"],
                "source": queued["source"],
                "delivery_attempt": queued["delivery_attempt"],
            },
            error_code="EVENT_RETRY_EXHAUSTED",
            error_message="failed",
        )

        replayed = store.replay_dlq(limit=10, force_replay=False)
        events = store.queue_events(checkpoint="default", source="webex-webhook", limit=10)

        assert replayed == 1
        assert len(events) == 2
        assert events[-1]["delivery_attempt"] == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)
