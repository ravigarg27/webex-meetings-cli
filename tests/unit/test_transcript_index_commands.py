import json
import shutil
from pathlib import Path
import sys
import types
import uuid

import pytest
import typer

from webex_cli.commands import transcript as transcript_commands
from webex_cli.errors import CliError, DomainCode
import webex_cli.transcript_index as transcript_index_module


class _TranscriptIndexClient:
    def list_meetings(self, *, from_utc, to_utc, page_size, page_token, host_email=None):  # noqa: ANN001
        return (
            [
                {"id": "m1", "title": "Alpha Sync", "start": "2026-01-01T10:00:00Z"},
                {"id": "m2", "title": "Budget Review", "start": "2026-01-02T10:00:00Z"},
            ],
            None,
        )

    def list_transcripts(self, meeting_id):
        return [{"id": f"t-{meeting_id}", "status": "ready"}]

    def download_transcript(self, transcript_id, format_value):
        payloads = {
            "t-m1": {
                "segments": [
                    {"id": "s1", "speaker": "Alice", "startOffsetMs": 0, "endOffsetMs": 1000, "text": "Alpha kickoff"},
                    {"id": "s2", "speaker": "Bob", "startOffsetMs": 1000, "endOffsetMs": 2000, "text": "Budget follow-up"},
                ]
            },
            "t-m2": {
                "segments": [
                    {"id": "s3", "speaker": "Alice", "startOffsetMs": 0, "endOffsetMs": 1200, "text": "Alpha budget alignment"},
                ]
            },
        }
        return json.dumps(payloads[transcript_id]).encode("utf-8")


class _TranscriptSearchUnavailableClient:
    def list_meetings(self, *, from_utc, to_utc, page_size, page_token, host_email=None):  # noqa: ANN001
        raise CliError(DomainCode.NO_ACCESS, "search unavailable")


def _temp_root() -> Path:
    root = Path(".test_tmp") / f"transcript-index-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _install_fake_keyring(monkeypatch) -> dict[tuple[str, str], str]:
    data: dict[tuple[str, str], str] = {}

    def _set_password(service, account, value):
        data[(service, account)] = value

    def _get_password(service, account):
        return data.get((service, account))

    def _delete_password(service, account):
        data.pop((service, account), None)

    monkeypatch.setitem(
        sys.modules,
        "keyring",
        types.SimpleNamespace(
            set_password=_set_password,
            get_password=_get_password,
            delete_password=_delete_password,
        ),
    )
    return data


def test_transcript_index_rebuild_then_search_falls_back_to_local_index(monkeypatch, capsys) -> None:
    root = _temp_root()
    monkeypatch.setenv("APPDATA", str(root))
    monkeypatch.setenv("WEBEX_SEARCH_LOCAL_INDEX_ENABLED", "1")
    _install_fake_keyring(monkeypatch)
    try:
        monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptIndexClient())
        transcript_commands.rebuild_index(from_value="2026-01-01", to_value="2026-01-03", json_output=True)
        rebuild_payload = json.loads(capsys.readouterr().out)
        assert rebuild_payload["data"]["indexed_transcripts"] == 2
        assert rebuild_payload["data"]["indexed_segments"] == 3

        monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptSearchUnavailableClient())
        transcript_commands.search_transcripts(
            query="alpha",
            meeting_id=None,
            speaker="Alice",
            from_value="2026-01-01",
            to_value="2026-01-03",
            filter_value=None,
            sort_value="started_at:desc",
            limit=10,
            max_pages=5,
            page_token=None,
            case_sensitive=False,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert [item["resource_id"] for item in payload["data"]["items"]] == ["t-m2", "t-m1"]
        assert "LOCAL_INDEX_FALLBACK" in payload["warnings"]
    finally:
        shutil.rmtree(root, ignore_errors=True)
        sys.modules.pop("keyring", None)


def test_transcript_search_without_upstream_or_index_returns_capability_error(monkeypatch, capsys) -> None:
    root = _temp_root()
    monkeypatch.setenv("APPDATA", str(root))
    monkeypatch.setenv("WEBEX_SEARCH_LOCAL_INDEX_ENABLED", "1")
    try:
        monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptSearchUnavailableClient())
        with pytest.raises(typer.Exit) as exc:
            transcript_commands.search_transcripts(
                query="alpha",
                meeting_id=None,
                speaker=None,
                from_value="2026-01-01",
                to_value="2026-01-03",
                filter_value=None,
                sort_value=None,
                limit=10,
                max_pages=5,
                page_token=None,
                case_sensitive=False,
                json_output=True,
            )
        payload = json.loads(capsys.readouterr().out)
        assert exc.value.exit_code == 5
        assert payload["error"]["code"] == "SEARCH_CAPABILITY_UNAVAILABLE"
        assert payload["error"]["details"]["fallback_command"] == "webex transcript index rebuild"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_transcript_index_key_rotate_reencrypts_existing_index(monkeypatch, capsys) -> None:
    root = _temp_root()
    monkeypatch.setenv("APPDATA", str(root))
    monkeypatch.setenv("WEBEX_SEARCH_LOCAL_INDEX_ENABLED", "1")
    keyring_data = _install_fake_keyring(monkeypatch)
    try:
        monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptIndexClient())
        transcript_commands.rebuild_index(from_value="2026-01-01", to_value="2026-01-03", json_output=True)
        capsys.readouterr()
        previous_keys = dict(keyring_data)

        transcript_commands.rotate_index_key(confirm=True, yes=False, json_output=True)
        payload = json.loads(capsys.readouterr().out)
        assert payload["data"]["reencrypted_segments"] == 3
        assert keyring_data != previous_keys

        monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptSearchUnavailableClient())
        transcript_commands.search_transcripts(
            query="alpha",
            meeting_id=None,
            speaker=None,
            from_value="2026-01-01",
            to_value="2026-01-03",
            filter_value=None,
            sort_value="started_at:desc",
            limit=10,
            max_pages=5,
            page_token=None,
            case_sensitive=False,
            json_output=True,
        )
        search_payload = json.loads(capsys.readouterr().out)
        assert [item["resource_id"] for item in search_payload["data"]["items"]] == ["t-m2", "t-m1"]
    finally:
        shutil.rmtree(root, ignore_errors=True)
        sys.modules.pop("keyring", None)


def test_transcript_index_key_rotate_falls_back_when_keyring_save_fails(monkeypatch, capsys) -> None:
    root = _temp_root()
    monkeypatch.setenv("APPDATA", str(root))
    monkeypatch.setenv("WEBEX_SEARCH_LOCAL_INDEX_ENABLED", "1")
    monkeypatch.setenv(transcript_index_module.INDEX_KEY_ALLOW_PLAINTEXT_ENV, "1")
    _install_fake_keyring(monkeypatch)
    try:
        monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptIndexClient())
        transcript_commands.rebuild_index(from_value="2026-01-01", to_value="2026-01-03", json_output=True)
        capsys.readouterr()

        def _flaky_save(profile: str, key: bytes) -> bool:
            return False

        monkeypatch.setattr(transcript_index_module, "_save_key_to_keyring", _flaky_save)
        transcript_commands.rotate_index_key(confirm=True, yes=False, json_output=True)

        payload = json.loads(capsys.readouterr().out)
        assert payload["data"]["key_backend"] == "fallback"
        assert transcript_index_module._plaintext_key_path("default").exists()

        monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptSearchUnavailableClient())
        transcript_commands.search_transcripts(
            query="alpha",
            meeting_id=None,
            speaker=None,
            from_value="2026-01-01",
            to_value="2026-01-03",
            filter_value=None,
            sort_value="started_at:desc",
            limit=10,
            max_pages=5,
            page_token=None,
            case_sensitive=False,
            json_output=True,
        )
        search_payload = json.loads(capsys.readouterr().out)
        assert [item["resource_id"] for item in search_payload["data"]["items"]] == ["t-m2", "t-m1"]
    finally:
        shutil.rmtree(root, ignore_errors=True)
        sys.modules.pop("keyring", None)
