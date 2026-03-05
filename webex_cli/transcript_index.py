from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from webex_cli.config.credentials import CredentialStore, SERVICE_NAME
from webex_cli.config.paths import profile_search_dir, search_index_db_path, search_meta_path
from webex_cli.errors import CliError, DomainCode
from webex_cli.utils.files import write_json_atomic

INDEX_KEY_ALLOW_PLAINTEXT_ENV = "WEBEX_SEARCH_LOCAL_INDEX_ALLOW_PLAINTEXT"
INDEX_KEY_ACCOUNT_SUFFIX = ":transcript-index-key"


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


def _plaintext_key_path(profile: str) -> Path:
    return profile_search_dir(profile) / "index-key.json"


def _keyring_available() -> bool:
    try:
        import keyring  # noqa: F401

        return True
    except Exception:
        return False


def _key_account(profile: str) -> str:
    return f"{profile}{INDEX_KEY_ACCOUNT_SUFFIX}"


def _load_key_from_keyring(profile: str) -> bytes | None:
    if not _keyring_available():
        return None
    try:
        import keyring

        encoded = keyring.get_password(SERVICE_NAME, _key_account(profile))
    except Exception:
        return None
    if not encoded:
        return None
    try:
        return base64.b64decode(encoded.encode("ascii"))
    except Exception:
        return None


def _save_key_to_keyring(profile: str, key: bytes) -> bool:
    if not _keyring_available():
        return False
    try:
        import keyring

        keyring.set_password(SERVICE_NAME, _key_account(profile), base64.b64encode(key).decode("ascii"))
        return True
    except Exception:
        return False


def _delete_key_from_keyring(profile: str) -> None:
    if not _keyring_available():
        return
    try:
        import keyring

        keyring.delete_password(SERVICE_NAME, _key_account(profile))
    except Exception:
        return


def _load_key_from_fallback(profile: str) -> bytes | None:
    path = _plaintext_key_path(profile)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if os.name == "nt" and isinstance(payload.get("key_dpapi"), str):
        try:
            encrypted = base64.b64decode(payload["key_dpapi"].encode("ascii"))
            return CredentialStore._dpapi_decrypt(encrypted)
        except Exception:
            return None
    encoded = payload.get("key")
    if not isinstance(encoded, str):
        return None
    try:
        return base64.b64decode(encoded.encode("ascii"))
    except Exception:
        return None


def _save_key_to_fallback(profile: str, key: bytes) -> None:
    if not _truthy(os.environ.get(INDEX_KEY_ALLOW_PLAINTEXT_ENV)):
        raise CliError(
            DomainCode.CAPABILITY_ERROR,
            "Secure keyring is unavailable for the local transcript index.",
            error_code="SEARCH_INDEX_ENCRYPTION_UNAVAILABLE",
            details={"fallback_env": INDEX_KEY_ALLOW_PLAINTEXT_ENV},
        )
    path = _plaintext_key_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        encrypted = CredentialStore._dpapi_encrypt(key)
        payload = {"key_dpapi": base64.b64encode(encrypted).decode("ascii")}
    else:
        payload = {"key": base64.b64encode(key).decode("ascii")}
    write_json_atomic(path, payload)


def _delete_fallback_key(profile: str) -> None:
    path = _plaintext_key_path(profile)
    if path.exists():
        path.unlink(missing_ok=True)


class TranscriptLocalIndex:
    def __init__(self, profile: str) -> None:
        self.profile = profile
        self.db_path = search_index_db_path(profile)
        self.meta_path = search_meta_path(profile)
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.meta_path.exists():
            write_json_atomic(
                self.meta_path,
                {
                    "version": "1.2",
                    "profile": self.profile,
                    "updated_at": _utc_now(),
                    "encrypted": True,
                },
            )
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS transcripts (
                    transcript_id TEXT PRIMARY KEY,
                    meeting_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    started_at TEXT,
                    indexed_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS segments (
                    transcript_id TEXT NOT NULL,
                    segment_id TEXT NOT NULL,
                    speaker_blob BLOB NOT NULL,
                    text_blob BLOB NOT NULL,
                    start_offset_ms INTEGER,
                    end_offset_ms INTEGER,
                    PRIMARY KEY (transcript_id, segment_id)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def exists(self) -> bool:
        if not self.db_path.exists():
            return False
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()
        return int(row[0]) > 0

    def _load_meta(self) -> dict[str, Any]:
        if not self.meta_path.exists():
            return {}
        try:
            payload = json.loads(self.meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_meta(self, updates: dict[str, Any]) -> None:
        payload = self._load_meta()
        payload.update(updates)
        payload["profile"] = self.profile
        payload["version"] = "1.2"
        payload["updated_at"] = _utc_now()
        write_json_atomic(self.meta_path, payload)

    def _load_key(self) -> tuple[bytes | None, str | None]:
        key = _load_key_from_keyring(self.profile)
        if key is not None:
            return key, "keyring"
        key = _load_key_from_fallback(self.profile)
        if key is not None:
            return key, "fallback"
        return None, None

    def _require_key(self) -> tuple[bytes, str]:
        key, backend = self._load_key()
        if key is None or backend is None:
            raise CliError(
                DomainCode.STATE_ERROR,
                "Local transcript index key is missing. Rebuild the index.",
                error_code="SEARCH_INDEX_KEY_MISSING",
                details={"fallback_command": "webex transcript index rebuild"},
            )
        return key, backend

    def _ensure_key(self) -> tuple[bytes, str]:
        key, backend = self._load_key()
        if key is not None and backend is not None:
            return key, backend
        key = AESGCM.generate_key(bit_length=256)
        if _save_key_to_keyring(self.profile, key):
            backend = "keyring"
        else:
            _save_key_to_fallback(self.profile, key)
            backend = "fallback"
        return key, backend

    def _encrypt(self, key: bytes, value: str) -> bytes:
        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(nonce, value.encode("utf-8"), None)
        return nonce + ciphertext

    def _decrypt(self, key: bytes, blob: bytes) -> str:
        try:
            nonce = blob[:12]
            ciphertext = blob[12:]
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
            return plaintext.decode("utf-8")
        except Exception as exc:
            raise CliError(
                DomainCode.STATE_ERROR,
                "Local transcript index could not be decrypted. Rotate or rebuild the index.",
                error_code="SEARCH_INDEX_KEY_INVALID",
                details={"fallback_command": "webex transcript index rebuild"},
            ) from exc

    def replace_all(self, records: list[dict[str, Any]], *, from_utc: str, to_utc: str) -> dict[str, Any]:
        key, backend = self._ensure_key()
        transcript_count = 0
        segment_count = 0
        with self._connect() as conn:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM segments")
            conn.execute("DELETE FROM transcripts")
            for record in records:
                conn.execute(
                    """
                    INSERT INTO transcripts(transcript_id, meeting_id, title, started_at, indexed_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        record["transcript_id"],
                        record["meeting_id"],
                        record["title"],
                        record.get("started_at"),
                        _utc_now(),
                    ),
                )
                transcript_count += 1
                for segment in record["segments"]:
                    conn.execute(
                        """
                        INSERT INTO segments(transcript_id, segment_id, speaker_blob, text_blob, start_offset_ms, end_offset_ms)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record["transcript_id"],
                            segment["segment_id"],
                            self._encrypt(key, str(segment.get("speaker") or "")),
                            self._encrypt(key, str(segment.get("text") or "")),
                            segment.get("start_offset_ms"),
                            segment.get("end_offset_ms"),
                        ),
                    )
                    segment_count += 1
            conn.commit()
        self._save_meta(
            {
                "encrypted": True,
                "key_backend": backend,
                "last_built_at": _utc_now(),
                "last_from_utc": from_utc,
                "last_to_utc": to_utc,
                "indexed_transcripts": transcript_count,
                "indexed_segments": segment_count,
            }
        )
        return {
            "indexed_transcripts": transcript_count,
            "indexed_segments": segment_count,
            "from": from_utc,
            "to": to_utc,
            "key_backend": backend,
        }

    def is_stale(self, threshold_hours: int) -> bool:
        if threshold_hours < 1:
            threshold_hours = 1
        payload = self._load_meta()
        raw = payload.get("last_built_at")
        if not isinstance(raw, str):
            return True
        try:
            from datetime import datetime, timedelta, timezone

            built_at = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return True
        return built_at + timedelta(hours=threshold_hours) < datetime.now(timezone.utc)

    def search_rows(self, *, from_utc: str, to_utc: str, meeting_id: str | None = None) -> list[dict[str, Any]]:
        key, _ = self._require_key()
        clauses = ["(t.started_at IS NULL OR (t.started_at >= ? AND t.started_at <= ?))"]
        params: list[Any] = [from_utc, to_utc]
        if meeting_id is not None:
            clauses.append("t.meeting_id = ?")
            params.append(meeting_id)
        where_sql = " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    t.transcript_id,
                    t.meeting_id,
                    t.title,
                    t.started_at,
                    s.segment_id,
                    s.speaker_blob,
                    s.text_blob,
                    s.start_offset_ms,
                    s.end_offset_ms
                FROM transcripts t
                JOIN segments s ON s.transcript_id = t.transcript_id
                WHERE {where_sql}
                ORDER BY t.started_at DESC, t.transcript_id ASC, s.segment_id ASC
                """,
                tuple(params),
            ).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            items.append(
                {
                    "transcript_id": str(row["transcript_id"]),
                    "meeting_id": str(row["meeting_id"]),
                    "title": str(row["title"]),
                    "started_at": row["started_at"],
                    "segment_id": str(row["segment_id"]),
                    "speaker": self._decrypt(key, row["speaker_blob"]),
                    "text": self._decrypt(key, row["text_blob"]),
                    "start_offset_ms": row["start_offset_ms"],
                    "end_offset_ms": row["end_offset_ms"],
                }
            )
        return items

    def rotate_key(self) -> dict[str, Any]:
        old_key, old_backend = self._require_key()
        new_key = AESGCM.generate_key(bit_length=256)
        if not self.exists():
            if _save_key_to_keyring(self.profile, new_key):
                backend = "keyring"
            else:
                _save_key_to_fallback(self.profile, new_key)
                backend = "fallback"
            self._save_meta({"key_backend": backend, "last_rotated_at": _utc_now()})
            return {"reencrypted_segments": 0, "key_backend": backend}

        with self._connect() as conn:
            rows = conn.execute("SELECT transcript_id, segment_id, speaker_blob, text_blob FROM segments").fetchall()
            updates: list[tuple[bytes, bytes, str, str]] = []
            for row in rows:
                speaker = self._decrypt(old_key, row["speaker_blob"])
                text = self._decrypt(old_key, row["text_blob"])
                updates.append(
                    (
                        self._encrypt(new_key, speaker),
                        self._encrypt(new_key, text),
                        str(row["transcript_id"]),
                        str(row["segment_id"]),
                    )
                )
            conn.execute("BEGIN")
            conn.executemany(
                "UPDATE segments SET speaker_blob = ?, text_blob = ? WHERE transcript_id = ? AND segment_id = ?",
                updates,
            )
            conn.commit()

        if _save_key_to_keyring(self.profile, new_key):
            backend = "keyring"
            _delete_fallback_key(self.profile)
        else:
            _save_key_to_fallback(self.profile, new_key)
            if old_backend == "keyring":
                _delete_key_from_keyring(self.profile)
            backend = "fallback"
        self._save_meta({"key_backend": backend, "last_rotated_at": _utc_now()})
        return {"reencrypted_segments": len(updates), "key_backend": backend}
