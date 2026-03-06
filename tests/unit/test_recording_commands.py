import json
import shutil
import uuid
from pathlib import Path

import pytest
import typer

from webex_cli.commands import recording as recording_commands
from webex_cli.errors import CliError, DomainCode


class _AmbiguousRecordingClient:
    def list_recordings_for_meeting(self, meeting_id):
        return [{"id": "r1"}, {"id": "r2"}]


class _DownloadRecordingClient:
    def list_recordings_for_meeting(self, meeting_id):
        return [{"id": "r1"}]

    def download_recording(self, recording_id, quality):
        return (b"abc", "medium")

    def download_recording_to_file(self, recording_id, quality, output_path, *, overwrite, checksum=None):
        output_path.write_bytes(b"abc")
        return "medium"


class _DownloadRecordingChecksumClient:
    def list_recordings_for_meeting(self, meeting_id):
        return [{"id": "r1", "checksum_sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}]

    def download_recording(self, recording_id, quality):
        return (b"abc", "best")

    def download_recording_to_file(self, recording_id, quality, output_path, *, overwrite, checksum=None):
        content = b"abc"
        if checksum is not None:
            algorithm, expected = checksum
            import hashlib

            digest = hashlib.new(algorithm)
            digest.update(content)
            if digest.hexdigest() != expected:
                raise CliError(DomainCode.DOWNLOAD_FAILED, "Downloaded file checksum mismatch.")
        output_path.write_bytes(content)
        return "best"


class _RecordingStatusNoFieldClient:
    def list_recordings_for_meeting(self, meeting_id):
        return [{"id": "r1"}]


class _MismatchedRecordingClient:
    def get_recording(self, recording_id):
        return {"id": recording_id, "meetingId": "other-meeting"}


class _UnknownRecordingStatusClient:
    def list_recordings_for_meeting(self, meeting_id):
        return [{"id": "r1", "status": "future_status"}]


class _SinglePageRecordingClient:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def list_recordings(self, *, from_utc, to_utc, page_size, page_token, host_email=None, meeting_id=None):  # noqa: ANN001
        self.calls.append(page_token)
        return (
            [
                {
                    "id": "r9",
                    "meetingId": "m9",
                    "createTime": "2026-01-03T10:00:00Z",
                    "durationSeconds": 300,
                    "sizeBytes": 1024,
                }
            ],
            "next-recording-token",
        )


class _RecordingListClient:
    def list_recordings(self, *, from_utc, to_utc, page_size, page_token, host_email=None, meeting_id=None):  # noqa: ANN001
        return (
            [
                {
                    "id": "r1",
                    "meetingId": "m1",
                    "occurrenceId": "occ-1",
                    "createTime": "2026-01-03T10:00:00Z",
                    "durationSeconds": 300,
                    "sizeBytes": 1024,
                    "downloadUrl": "https://example.test/file.mp4",
                }
            ],
            None,
        )


class _RecordingSearchClient:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def list_recordings(self, *, from_utc, to_utc, page_size, page_token, host_email=None, meeting_id=None):  # noqa: ANN001
        self.calls.append(page_token)
        if page_token is None:
            return (
                [
                    {
                        "id": "r1",
                        "meetingId": "m1",
                        "topic": "Board Review",
                        "createTime": "2026-01-03T10:00:00Z",
                        "durationSeconds": 300,
                        "sizeBytes": 1024,
                        "downloadUrl": "https://example.test/r1.mp4",
                    },
                    {
                        "id": "r2",
                        "meetingId": "m2",
                        "topic": "Daily Sync",
                        "createTime": "2026-01-02T10:00:00Z",
                        "durationSeconds": 120,
                        "sizeBytes": 512,
                    },
                ],
                "next-recording-token",
            )
        return (
            [
                {
                    "id": "r3",
                    "meetingId": "m3",
                    "topic": "board followup",
                    "createTime": "2026-01-01T10:00:00Z",
                    "durationSeconds": 180,
                    "sizeBytes": 2048,
                    "downloadUrl": "https://example.test/r3.mp4",
                }
            ],
            None,
        )


class _DownloadRecordingMd5OnlyClient(_DownloadRecordingChecksumClient):
    def list_recordings_for_meeting(self, meeting_id):
        return [{"id": "r1", "checksum_md5": "900150983cd24fb0d6963f7d28e17f72"}]


def test_recording_status_ambiguous_exits_2(monkeypatch) -> None:
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _AmbiguousRecordingClient())
    with pytest.raises(typer.Exit) as exc:
        recording_commands.status_recording(meeting_id="m1", recording_id=None, json_output=True)
    assert exc.value.exit_code == 2


def test_recording_download_quality_fallback_warning(monkeypatch, capsys) -> None:
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _DownloadRecordingClient())
    tmp_dir = Path(".test_tmp") / f"recording-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / "out.mp4"
    try:
        recording_commands.download_recording(
            meeting_id="m1",
            out=str(target),
            recording_id=None,
            quality="best",
            verify_checksum=False,
            overwrite=False,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["warnings"] == ["QUALITY_FALLBACK"]
        assert payload["data"]["quality"] == "medium"
        assert target.exists()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_recording_list_with_page_token_returns_single_page_and_next_token(monkeypatch, capsys) -> None:
    client = _SinglePageRecordingClient()
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: client)
    recording_commands.list_recordings(
        from_value="2026-01-01",
        to_value="2026-01-04",
        last=None,
        tz="UTC",
        page_size=10,
        page_token="resume-token",
        json_output=True,
    )
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["data"]["items"]) == 1
    assert payload["data"]["items"][0]["recording_id"] == "r9"
    assert payload["data"]["next_page_token"] == "next-recording-token"
    assert client.calls == ["resume-token"]


def test_recording_list_uses_spec_schema_fields(monkeypatch, capsys) -> None:
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _RecordingListClient())
    recording_commands.list_recordings(
        from_value="2026-01-01",
        to_value="2026-01-04",
        last=None,
        tz="UTC",
        page_size=50,
        page_token=None,
        json_output=True,
    )
    payload = json.loads(capsys.readouterr().out)
    item = payload["data"]["items"][0]
    assert item["recording_id"] == "r1"
    assert item["meeting_id"] == "m1"
    assert item["occurrence_id"] == "occ-1"
    assert item["duration_seconds"] == 300
    assert item["size_bytes"] == 1024
    assert item["downloadable"] is True


def test_recording_status_without_status_defaults_processing(monkeypatch, capsys) -> None:
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _RecordingStatusNoFieldClient())
    recording_commands.status_recording(meeting_id="m1", recording_id=None, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "processing"


def test_recording_status_rejects_meeting_recording_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _MismatchedRecordingClient())
    with pytest.raises(typer.Exit) as exc:
        recording_commands.status_recording(meeting_id="m1", recording_id="r1", json_output=True)
    assert exc.value.exit_code == 2


def test_recording_status_unknown_status_warns(monkeypatch, capsys) -> None:
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _UnknownRecordingStatusClient())
    recording_commands.status_recording(meeting_id="m1", recording_id=None, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "failed"
    assert payload["warnings"] == ["UNMAPPED_RECORDING_STATUS"]


def test_normalize_recording_parses_float_strings_for_size_and_duration() -> None:
    item = recording_commands._normalize_recording(
        {
            "id": "r1",
            "meetingId": "m1",
            "durationSeconds": "300.0",
            "sizeBytes": "1024.0",
        }
    )
    assert item["duration_seconds"] == 300
    assert item["size_bytes"] == 1024


def test_normalize_recording_preserves_zero_values() -> None:
    item = recording_commands._normalize_recording(
        {
            "id": "r1",
            "meetingId": "m1",
            "durationSeconds": 0,
            "sizeBytes": 0,
        }
    )
    assert item["duration_seconds"] == 0
    assert item["size_bytes"] == 0


def test_recording_download_verify_checksum_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _DownloadRecordingChecksumClient())
    tmp_dir = Path(".test_tmp") / f"recording-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / "out.mp4"
    try:
        recording_commands.download_recording(
            meeting_id="m1",
            out=str(target),
            recording_id=None,
            quality="best",
            verify_checksum=True,
            overwrite=False,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_recording_download_verify_checksum_mismatch(monkeypatch) -> None:
    class _MismatchClient(_DownloadRecordingChecksumClient):
        def download_recording_to_file(self, recording_id, quality, output_path, *, overwrite, checksum=None):
            content = b"zzz"
            if checksum is not None:
                algorithm, expected = checksum
                import hashlib

                digest = hashlib.new(algorithm)
                digest.update(content)
                if digest.hexdigest() != expected:
                    raise CliError(DomainCode.DOWNLOAD_FAILED, "Downloaded file checksum mismatch.")
            output_path.write_bytes(content)
            return "best"

    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _MismatchClient())
    tmp_dir = Path(".test_tmp") / f"recording-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / "out.mp4"
    try:
        with pytest.raises(typer.Exit) as exc:
            recording_commands.download_recording(
                meeting_id="m1",
                out=str(target),
                recording_id=None,
                quality="best",
                verify_checksum=True,
                overwrite=False,
                json_output=True,
            )
        assert exc.value.exit_code == 10
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_recording_download_ignores_md5_only_metadata(monkeypatch, capsys) -> None:
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: _DownloadRecordingMd5OnlyClient())
    tmp_dir = Path(".test_tmp") / f"recording-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / "out.mp4"
    try:
        recording_commands.download_recording(
            meeting_id="m1",
            out=str(target),
            recording_id=None,
            quality="best",
            verify_checksum=True,
            overwrite=False,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["warnings"] == ["CHECKSUM_METADATA_MISSING"]
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_recording_search_applies_query_filter_sort_and_contract(monkeypatch, capsys) -> None:
    client = _RecordingSearchClient()
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: client)
    recording_commands.search_recordings(
        query="board",
        from_value="2026-01-01",
        to_value="2026-01-04",
        filter_value="downloadable=true AND size_bytes>=1024",
        sort_value="started_at:desc",
        limit=10,
        max_pages=5,
        page_token=None,
        case_sensitive=False,
        json_output=True,
    )
    payload = json.loads(capsys.readouterr().out)
    assert [item["resource_id"] for item in payload["data"]["items"]] == ["r1", "r3"]
    assert payload["data"]["items"][0]["resource_type"] == "recording"
    assert payload["data"]["items"][0]["title"] == "Board Review"
    assert payload["data"]["items"][0]["snippet"] == "Board Review"
    assert payload["data"]["items"][0]["sort_key"] == "2026-01-03T10:00:00Z"
    assert payload["data"]["next_page_token"] is None
    assert client.calls == [None, "next-recording-token"]


def test_recording_search_with_page_token_fetches_single_page(monkeypatch, capsys) -> None:
    client = _RecordingSearchClient()
    monkeypatch.setattr(recording_commands, "build_client", lambda token=None: client)
    recording_commands.search_recordings(
        query="board",
        from_value="2026-01-01",
        to_value="2026-01-04",
        filter_value=None,
        sort_value=None,
        limit=10,
        max_pages=5,
        page_token="resume-token",
        case_sensitive=False,
        json_output=True,
    )
    payload = json.loads(capsys.readouterr().out)
    assert [item["resource_id"] for item in payload["data"]["items"]] == ["r3"]
    assert payload["data"]["next_page_token"] is None
    assert client.calls == ["resume-token"]
