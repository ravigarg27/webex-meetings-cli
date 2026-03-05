from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
from typing import Any

from webex_cli.config.paths import (
    events_checkpoint_db_path,
    events_dedupe_db_path,
    events_dlq_db_path,
    events_meta_path,
    events_queue_db_path,
)
from webex_cli.config.options import resolve_option
from webex_cli.errors import CliError, DomainCode
from webex_cli.utils.files import write_json_atomic


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_event(payload: dict[str, Any], *, source: str, delivery_attempt: int = 1, source_record: int | None = None) -> dict[str, Any]:
    event_id = str(
        payload.get("id")
        or payload.get("eventId")
        or payload.get("event_id")
        or hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    )
    event_type = str(payload.get("event") or payload.get("eventType") or payload.get("resourceEvent") or "unknown")
    occurred_at = str(payload.get("created") or payload.get("occurredAt") or payload.get("occurred_at") or _utc_now())
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    resource_id = str(data.get("id") or payload.get("resourceId") or payload.get("resource_id") or "")
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "resource_id": resource_id,
        "payload": payload,
        "source": source,
        "delivery_attempt": delivery_attempt,
        "source_record": source_record,
    }


def validate_webhook_signature(payload_bytes: bytes, headers: dict[str, Any], secret: str) -> None:
    signature = None
    for key, value in headers.items():
        if str(key).lower() in {"x-spark-signature", "x-webex-signature"}:
            signature = str(value)
            break
    if not signature:
        return
    candidates = {
        hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha1).hexdigest(),
        hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest(),
    }
    if signature not in candidates:
        raise CliError(DomainCode.VALIDATION_ERROR, "Webhook signature was invalid.", error_code="EVENT_SIGNATURE_INVALID")


class EventStore:
    def __init__(self, profile: str) -> None:
        self.profile = profile
        self.queue_path = events_queue_db_path(profile)
        self.dedupe_path = events_dedupe_db_path(profile)
        self.dlq_path = events_dlq_db_path(profile)
        self.checkpoint_path = events_checkpoint_db_path(profile)
        self.meta_path = events_meta_path(profile)
        self._ensure_meta()
        self._ensure_queue_db()
        self._ensure_dedupe_db()
        self._ensure_dlq_db()
        self._ensure_checkpoint_db()

    def _ensure_meta(self) -> None:
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.meta_path.exists():
            write_json_atomic(self.meta_path, {"version": "1.2", "profile": self.profile, "updated_at": _utc_now()})

    def _connect(self, path: Path) -> sqlite3.Connection:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _ensure_queue_db(self) -> None:
        with self._connect(self.queue_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    resource_id TEXT,
                    payload_json TEXT NOT NULL,
                    headers_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_record INTEGER,
                    delivery_attempt INTEGER NOT NULL,
                    inserted_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_seq ON events(seq)")

    def _ensure_dedupe_db(self) -> None:
        with self._connect(self.dedupe_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dedupe (
                    event_id TEXT PRIMARY KEY,
                    seen_at TEXT NOT NULL
                )
                """
            )

    def _ensure_dlq_db(self) -> None:
        with self._connect(self.dlq_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dlq (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_seq INTEGER,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    resource_id TEXT,
                    payload_json TEXT NOT NULL,
                    headers_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    delivery_attempt INTEGER NOT NULL,
                    error_code TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    replayed_at TEXT,
                    inserted_at TEXT NOT NULL
                )
                """
            )

    def _ensure_checkpoint_db(self) -> None:
        with self._connect(self.checkpoint_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint TEXT NOT NULL,
                    source TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (checkpoint, source)
                )
                """
            )

    def _dedupe_ttl_hours(self) -> int:
        return int(
            resolve_option(
                None,
                "WEBEX_EVENTS_DEDUPE_TTL_HOURS",
                "events.dedupe_ttl_hours",
                "events_dedupe_ttl_hours",
                default=24,
                value_type="int",
            )
        )

    def _prune_expired_dedupe(self, conn: sqlite3.Connection) -> None:
        ttl_hours = self._dedupe_ttl_hours()
        if ttl_hours <= 0:
            return
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=ttl_hours)).isoformat()
        conn.execute("DELETE FROM dedupe WHERE seen_at < ?", (cutoff,))
        conn.commit()

    def append_event(
        self,
        payload: dict[str, Any],
        *,
        headers: dict[str, Any],
        source: str,
        delivery_attempt: int = 1,
        source_record: int | None = None,
        force: bool = False,
    ) -> dict[str, Any] | None:
        event = _normalize_event(payload, source=source, delivery_attempt=delivery_attempt, source_record=source_record)
        with self._connect(self.dedupe_path) as dedupe_conn:
            self._prune_expired_dedupe(dedupe_conn)
            row = dedupe_conn.execute("SELECT event_id FROM dedupe WHERE event_id = ?", (event["event_id"],)).fetchone()
            if row is not None and not force:
                return None
            dedupe_conn.execute(
                "INSERT OR REPLACE INTO dedupe(event_id, seen_at) VALUES (?, ?)",
                (event["event_id"], _utc_now()),
            )
            dedupe_conn.commit()
        with self._connect(self.queue_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO events(event_id, event_type, occurred_at, resource_id, payload_json, headers_json, source, source_record, delivery_attempt, inserted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    event["event_type"],
                    event["occurred_at"],
                    event["resource_id"],
                    json.dumps(event["payload"], sort_keys=True),
                    json.dumps(headers, sort_keys=True),
                    event["source"],
                    event["source_record"],
                    event["delivery_attempt"],
                    _utc_now(),
                ),
            )
            conn.commit()
        event["seq"] = int(cursor.lastrowid)
        event["headers"] = headers
        return event

    def _row_to_event(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "seq": int(row["seq"]),
            "event_id": str(row["event_id"]),
            "event_type": str(row["event_type"]),
            "occurred_at": str(row["occurred_at"]),
            "resource_id": str(row["resource_id"] or ""),
            "payload": json.loads(row["payload_json"]),
            "headers": json.loads(row["headers_json"]),
            "source": str(row["source"]),
            "source_record": row["source_record"],
            "delivery_attempt": int(row["delivery_attempt"]),
        }

    def queue_events(self, *, checkpoint: str, source: str, limit: int) -> list[dict[str, Any]]:
        start_value = self.get_checkpoint(checkpoint, source)
        start_seq = int(start_value or 0) if source == "webex-webhook" else 0
        with self._connect(self.queue_path) as conn:
            rows = conn.execute(
                """
                SELECT seq, event_id, event_type, occurred_at, resource_id, payload_json, headers_json, source, source_record, delivery_attempt
                FROM events
                WHERE source = ? AND seq > ?
                ORDER BY seq ASC
                LIMIT ?
                """,
                (source, start_seq, limit),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def write_dlq(self, event: dict[str, Any], *, error_code: str, error_message: str) -> None:
        with self._connect(self.dlq_path) as conn:
            conn.execute(
                """
                INSERT INTO dlq(original_seq, event_id, event_type, occurred_at, resource_id, payload_json, headers_json, source, delivery_attempt, error_code, error_message, inserted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get("seq"),
                    event["event_id"],
                    event["event_type"],
                    event["occurred_at"],
                    event.get("resource_id"),
                    json.dumps(event["payload"], sort_keys=True),
                    json.dumps(event.get("headers") or {}, sort_keys=True),
                    event["source"],
                    int(event.get("delivery_attempt") or 1),
                    error_code,
                    error_message,
                    _utc_now(),
                ),
            )
            conn.commit()

    def list_dlq(self, limit: int) -> list[dict[str, Any]]:
        with self._connect(self.dlq_path) as conn:
            rows = conn.execute(
                """
                SELECT id, original_seq, event_id, event_type, occurred_at, resource_id, payload_json, headers_json, source, delivery_attempt, error_code, error_message, replayed_at, inserted_at
                FROM dlq
                ORDER BY id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            items.append(
                {
                    "id": int(row["id"]),
                    "original_seq": row["original_seq"],
                    "event_id": str(row["event_id"]),
                    "event_type": str(row["event_type"]),
                    "occurred_at": str(row["occurred_at"]),
                    "resource_id": str(row["resource_id"] or ""),
                    "payload": json.loads(row["payload_json"]),
                    "headers": json.loads(row["headers_json"]),
                    "source": str(row["source"]),
                    "delivery_attempt": int(row["delivery_attempt"]),
                    "error_code": str(row["error_code"]),
                    "error_message": str(row["error_message"]),
                    "replayed_at": row["replayed_at"],
                    "inserted_at": str(row["inserted_at"]),
                }
            )
        return items

    def purge_dlq(self, older_than: str | None) -> int:
        with self._connect(self.dlq_path) as conn:
            if older_than:
                cursor = conn.execute("DELETE FROM dlq WHERE inserted_at < ?", (older_than,))
            else:
                cursor = conn.execute("DELETE FROM dlq")
            conn.commit()
            return cursor.rowcount

    def get_checkpoint(self, checkpoint: str, source: str) -> str | None:
        with self._connect(self.checkpoint_path) as conn:
            row = conn.execute(
                "SELECT value FROM checkpoints WHERE checkpoint = ? AND source = ?",
                (checkpoint, source),
            ).fetchone()
        if row is None:
            return None
        return str(row["value"])

    def commit_checkpoint(self, checkpoint: str, source: str, value: str) -> None:
        with self._connect(self.checkpoint_path) as conn:
            conn.execute(
                """
                INSERT INTO checkpoints(checkpoint, source, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(checkpoint, source) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (checkpoint, source, value, _utc_now()),
            )
            conn.commit()

    def reset_checkpoint(self, checkpoint: str) -> int:
        with self._connect(self.checkpoint_path) as conn:
            cursor = conn.execute("DELETE FROM checkpoints WHERE checkpoint = ?", (checkpoint,))
            conn.commit()
            return cursor.rowcount

    def replay_dlq(self, *, limit: int, force_replay: bool) -> int:
        where_sql = "" if force_replay else "WHERE replayed_at IS NULL"
        with self._connect(self.dlq_path) as conn:
            rows = conn.execute(
                """
                SELECT id, original_seq, event_id, event_type, occurred_at, resource_id, payload_json, headers_json, source, delivery_attempt, error_code, error_message, replayed_at, inserted_at
                FROM dlq
                """
                + where_sql
                + """
                ORDER BY id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items = [
            {
                "id": int(row["id"]),
                "original_seq": row["original_seq"],
                "event_id": str(row["event_id"]),
                "event_type": str(row["event_type"]),
                "occurred_at": str(row["occurred_at"]),
                "resource_id": str(row["resource_id"] or ""),
                "payload": json.loads(row["payload_json"]),
                "headers": json.loads(row["headers_json"]),
                "source": str(row["source"]),
                "delivery_attempt": int(row["delivery_attempt"]),
                "error_code": str(row["error_code"]),
                "error_message": str(row["error_message"]),
                "replayed_at": row["replayed_at"],
                "inserted_at": str(row["inserted_at"]),
            }
            for row in rows
        ]
        replayed = 0
        for item in items:
            event = self.append_event(
                item["payload"],
                headers=item["headers"],
                source=item["source"],
                delivery_attempt=int(item["delivery_attempt"]) + 1,
                force=True,
            )
            if event is None:
                continue
            with self._connect(self.dlq_path) as conn:
                conn.execute("UPDATE dlq SET replayed_at = ? WHERE id = ?", (_utc_now(), item["id"]))
                conn.commit()
            replayed += 1
        return replayed

    def status(self, checkpoint: str) -> dict[str, Any]:
        with self._connect(self.queue_path) as queue_conn, self._connect(self.dlq_path) as dlq_conn, self._connect(self.checkpoint_path) as cp_conn:
            dlq_depth = int(dlq_conn.execute("SELECT COUNT(*) FROM dlq").fetchone()[0])
            rows = cp_conn.execute("SELECT source, value FROM checkpoints WHERE checkpoint = ?", (checkpoint,)).fetchall()
            checkpoints = {str(row["source"]): {"value": str(row["value"])} for row in rows}
            webhook_checkpoint = int(checkpoints.get("webex-webhook", {}).get("value") or 0)
            queue_depth = int(
                queue_conn.execute(
                    "SELECT COUNT(*) FROM events WHERE source = ? AND seq > ?",
                    ("webex-webhook", webhook_checkpoint),
                ).fetchone()[0]
            )
        return {"checkpoint": checkpoint, "queue_depth": queue_depth, "dlq_depth": dlq_depth, "checkpoints": checkpoints}
