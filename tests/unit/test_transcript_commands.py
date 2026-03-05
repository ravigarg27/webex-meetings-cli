import json
import shutil
import time
from pathlib import Path
import uuid

import pytest
import typer

from webex_cli.commands import transcript as transcript_commands
from webex_cli.errors import CliError, DomainCode


class _TranscriptClientStatusNotFound:
    def list_transcripts(self, meeting_id):
        return []


class _TranscriptClientStatusMissing:
    def list_transcripts(self, meeting_id):
        return [{"id": "t1"}]


class _TranscriptClientWaitReady:
    def __init__(self) -> None:
        self.calls = 0

    def list_transcripts(self, meeting_id):
        self.calls += 1
        if self.calls == 1:
            return [{"id": "t1", "status": "processing"}]
        return [{"id": "t1", "status": "ready", "updatedAt": "2026-03-02T00:00:00Z"}]


class _TranscriptClientWaitNoAccess:
    def list_transcripts(self, meeting_id):
        raise CliError(DomainCode.NO_ACCESS, "forbidden")


class _TranscriptClientDisabled:
    def list_transcripts(self, meeting_id):
        raise CliError(DomainCode.TRANSCRIPT_DISABLED, "disabled")


class _TranscriptFormatClient:
    def __init__(self) -> None:
        self.last_format = None

    def list_transcripts(self, meeting_id):
        return [{"id": "t1"}]

    def download_transcript(self, transcript_id, format_value):
        self.last_format = format_value
        return b"ok"

    def download_transcript_to_file(self, transcript_id, format_value, output_path, *, overwrite, checksum=None):
        self.last_format = format_value
        output_path.write_bytes(b"ok")


class _TranscriptChecksumClient:
    def list_transcripts(self, meeting_id):
        return [{"id": "t1", "checksum_sha256": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"}]

    def download_transcript(self, transcript_id, format_value):
        return b"hello"

    def download_transcript_to_file(self, transcript_id, format_value, output_path, *, overwrite, checksum=None):
        content = b"hello"
        if checksum is not None:
            algorithm, expected = checksum
            import hashlib

            digest = hashlib.new(algorithm)
            digest.update(content)
            if digest.hexdigest() != expected:
                raise CliError(DomainCode.DOWNLOAD_FAILED, "Downloaded file checksum mismatch.")
        output_path.write_bytes(content)


class _BatchFailFastClient:
    def __init__(self) -> None:
        self.downloaded: list[str] = []

    def list_meetings(self, *, from_utc, to_utc, page_size, page_token, host_email=None):  # noqa: ANN001
        return (
            [
                {"id": "m1", "start": "2026-01-01T00:00:00Z"},
                {"id": "m2", "start": "2026-01-01T00:00:00Z"},
                {"id": "m3", "start": "2026-01-01T00:00:00Z"},
                {"id": "m4", "start": "2026-01-01T00:00:00Z"},
            ],
            None,
        )

    def list_transcripts(self, meeting_id):
        if meeting_id == "m1":
            time.sleep(0.05)
            return [{"id": "t1", "status": "ready"}]
        if meeting_id == "m2":
            return [{"id": "t2", "status": "ready"}]
        return [{"id": f"t-{meeting_id}", "status": "ready"}]

    def download_transcript_to_file(self, transcript_id, format_value, output_path, *, overwrite, checksum=None):
        if transcript_id == "t2":
            raise CliError(DomainCode.DOWNLOAD_FAILED, "download failed")
        self.downloaded.append(transcript_id)
        output_path.write_bytes(b"batch-data")


class _BatchThrottleClient:
    def __init__(self) -> None:
        self.calls = 0

    def list_meetings(self, *, from_utc, to_utc, page_size, page_token, host_email=None):  # noqa: ANN001
        return ([{"id": "m1"}, {"id": "m2"}], None)

    def list_transcripts(self, meeting_id):
        self.calls += 1
        if self.calls == 1:
            raise CliError(DomainCode.RATE_LIMITED, "rate limited")
        return [{"id": f"t-{meeting_id}", "status": "ready"}]

    def download_transcript_to_file(self, transcript_id, format_value, output_path, *, overwrite, checksum=None):
        output_path.write_bytes(b"ok")


class _BatchFailedStatusClient:
    def list_meetings(self, *, from_utc, to_utc, page_size, page_token, host_email=None):  # noqa: ANN001
        return (
            [
                {"id": "m1", "start": "2026-01-01T00:00:00Z"},
                {"id": "m2", "start": "2026-01-01T00:00:00Z"},
                {"id": "m3", "start": "2026-01-01T00:00:00Z"},
            ],
            None,
        )

    def list_transcripts(self, meeting_id):
        if meeting_id == "m2":
            return [{"id": "t2", "status": "failed"}]
        return [{"id": f"t-{meeting_id}", "status": "ready"}]

    def download_transcript_to_file(self, transcript_id, format_value, output_path, *, overwrite, checksum=None):
        output_path.write_bytes(b"ok")


class _BatchDeterministicFailFastClient:
    def list_meetings(self, *, from_utc, to_utc, page_size, page_token, host_email=None):  # noqa: ANN001
        return (
            [
                {"id": "m1", "start": "2026-01-01T00:00:00Z"},
                {"id": "m2", "start": "2026-01-01T00:00:00Z"},
                {"id": "m3", "start": "2026-01-01T00:00:00Z"},
            ],
            None,
        )

    def list_transcripts(self, meeting_id):
        return [{"id": f"t-{meeting_id}", "status": "ready"}]

    def download_transcript_to_file(self, transcript_id, format_value, output_path, *, overwrite, checksum=None):
        if transcript_id == "t-m1":
            time.sleep(0.05)
            raise CliError(DomainCode.NO_ACCESS, "no access")
        if transcript_id == "t-m2":
            raise CliError(DomainCode.DOWNLOAD_FAILED, "download failed")
        output_path.write_bytes(b"ok")


class _TranscriptSearchClient:
    def __init__(self) -> None:
        self.meeting_calls: list[str | None] = []
        self.download_calls: list[str] = []

    def list_meetings(self, *, from_utc, to_utc, page_size, page_token, host_email=None):  # noqa: ANN001
        self.meeting_calls.append(page_token)
        if page_token is None:
            return (
                [
                    {"id": "m1", "title": "Alpha Sync", "start": "2026-01-03T10:00:00Z"},
                    {"id": "m2", "title": "Budget Review", "start": "2026-01-02T10:00:00Z"},
                ],
                "next-token",
            )
        return (
            [
                {"id": "m3", "title": "Project Recap", "start": "2026-01-01T10:00:00Z"},
            ],
            None,
        )

    def list_transcripts(self, meeting_id):
        return [{"id": f"t-{meeting_id}", "status": "ready"}]

    def download_transcript(self, transcript_id, format_value):
        self.download_calls.append(transcript_id)
        payloads = {
            "t-m1": {
                "segments": [
                    {"id": "s1", "speaker": "Alice", "startOffsetMs": 0, "endOffsetMs": 1500, "text": "Alpha kickoff"},
                    {"id": "s2", "speaker": "Bob", "startOffsetMs": 1500, "endOffsetMs": 3000, "text": "Budget review"},
                ]
            },
            "t-m2": {
                "segments": [
                    {"id": "s3", "speaker": "Bob", "startOffsetMs": 0, "endOffsetMs": 1500, "text": "No alpha here"},
                ]
            },
            "t-m3": {
                "segments": [
                    {"id": "s4", "speaker": "Alice", "startOffsetMs": 0, "endOffsetMs": 2000, "text": "alpha follow up"},
                    {"id": "s5", "startOffsetMs": 2500, "endOffsetMs": 3000, "text": "Unattributed note"},
                ]
            },
        }
        return json.dumps(payloads[transcript_id]).encode("utf-8")


class _TranscriptSegmentsUnavailableClient:
    def list_transcripts(self, meeting_id):
        return [{"id": "t1", "status": "ready"}]

    def download_transcript(self, transcript_id, format_value):
        return json.dumps({"items": []}).encode("utf-8")


def test_transcript_status_maps_not_found(monkeypatch, capsys) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptClientStatusNotFound())
    transcript_commands.status(meeting_id="m1", json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "not_found"


def test_transcript_status_missing_defaults_to_processing(monkeypatch, capsys) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptClientStatusMissing())
    transcript_commands.status(meeting_id="m1", json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "processing"
    assert "TRANSCRIPT_STATUS_MISSING" in payload["warnings"]


def test_transcript_wait_processing_to_ready(monkeypatch, capsys) -> None:
    client = _TranscriptClientWaitReady()
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: client)
    monkeypatch.setattr(transcript_commands.time, "sleep", lambda _: None)
    transcript_commands.wait_transcript(meeting_id="m1", timeout=10, interval=1, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "ready"
    assert client.calls == 2


def test_transcript_wait_no_access_exits_5(monkeypatch) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptClientWaitNoAccess())
    with pytest.raises(typer.Exit) as exc:
        transcript_commands.wait_transcript(meeting_id="m1", timeout=10, interval=1, json_output=True)
    assert exc.value.exit_code == 5


def test_transcript_status_disabled_mapping(monkeypatch, capsys) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptClientDisabled())
    transcript_commands.status(meeting_id="m1", json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "transcript_disabled"


def test_transcript_get_accepts_txt_alias(monkeypatch, capsys) -> None:
    client = _TranscriptFormatClient()
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: client)
    transcript_commands.get_transcript(meeting_id="m1", format_value="txt", json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["format"] == "text"
    assert client.last_format == "text"


def test_transcript_download_accepts_text_alias(monkeypatch, capsys) -> None:
    client = _TranscriptFormatClient()
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: client)
    tmp_dir = Path(".test_tmp") / f"transcript-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path = tmp_dir / "out.txt"
    try:
        transcript_commands.download_transcript(
            meeting_id="m1",
            format_value="text",
            out=str(out_path),
            overwrite=False,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["data"]["format"] == "txt"
        assert client.last_format == "text"
        assert out_path.exists()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_transcript_download_txt_alias_uses_text_api_format(monkeypatch, capsys) -> None:
    client = _TranscriptFormatClient()
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: client)
    tmp_dir = Path(".test_tmp") / f"transcript-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path = tmp_dir / "out.txt"
    try:
        transcript_commands.download_transcript(
            meeting_id="m1",
            format_value="txt",
            out=str(out_path),
            overwrite=False,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["data"]["format"] == "txt"
        assert client.last_format == "text"
        assert out_path.exists()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_transcript_download_verify_checksum_success(monkeypatch, capsys) -> None:
    client = _TranscriptChecksumClient()
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: client)
    tmp_dir = Path(".test_tmp") / f"transcript-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path = tmp_dir / "out.txt"
    try:
        transcript_commands.download_transcript(
            meeting_id="m1",
            format_value="txt",
            out=str(out_path),
            verify_checksum=True,
            overwrite=False,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert out_path.exists()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_transcript_download_verify_checksum_mismatch(monkeypatch) -> None:
    class _MismatchClient(_TranscriptChecksumClient):
        def download_transcript_to_file(self, transcript_id, format_value, output_path, *, overwrite, checksum=None):
            content = b"not-hello"
            if checksum is not None:
                algorithm, expected = checksum
                import hashlib

                digest = hashlib.new(algorithm)
                digest.update(content)
                if digest.hexdigest() != expected:
                    raise CliError(DomainCode.DOWNLOAD_FAILED, "Downloaded file checksum mismatch.")
            output_path.write_bytes(content)

    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _MismatchClient())
    tmp_dir = Path(".test_tmp") / f"transcript-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path = tmp_dir / "out.txt"
    try:
        with pytest.raises(typer.Exit) as exc:
            transcript_commands.download_transcript(
                meeting_id="m1",
                format_value="txt",
                out=str(out_path),
                verify_checksum=True,
                overwrite=False,
                json_output=True,
            )
        assert exc.value.exit_code == 10
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_transcript_segments_filters_and_normalizes(monkeypatch, capsys) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptSearchClient())
    transcript_commands.segments(
        meeting_id="m1",
        speaker="alice",
        contains="alpha",
        from_offset=0,
        to_offset=2,
        case_sensitive=False,
        json_output=True,
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["items"] == [
        {
            "segment_id": "s1",
            "speaker": "Alice",
            "start_offset_ms": 0,
            "end_offset_ms": 1500,
            "text": "Alpha kickoff",
        }
    ]


def test_transcript_speakers_aggregates_deterministically(monkeypatch, capsys) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptSearchClient())
    transcript_commands.speakers(meeting_id="m3", json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["items"] == [
        {"speaker": "(Unknown)", "segment_count": 1, "total_duration_ms": 500},
        {"speaker": "Alice", "segment_count": 1, "total_duration_ms": 2000},
    ]


def test_transcript_segments_missing_metadata_returns_capability_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptSegmentsUnavailableClient())
    with pytest.raises(typer.Exit) as exc:
        transcript_commands.segments(meeting_id="m1", json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert exc.value.exit_code == 5
    assert payload["error"]["code"] == "TRANSCRIPT_SEGMENTS_UNAVAILABLE"


def test_transcript_speakers_missing_metadata_returns_capability_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _TranscriptSegmentsUnavailableClient())
    with pytest.raises(typer.Exit) as exc:
        transcript_commands.speakers(meeting_id="m1", json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert exc.value.exit_code == 5
    assert payload["error"]["code"] == "TRANSCRIPT_SEGMENTS_UNAVAILABLE"


def test_transcript_search_applies_query_filter_sort_and_contract(monkeypatch, capsys) -> None:
    client = _TranscriptSearchClient()
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: client)
    transcript_commands.search_transcripts(
        query="alpha",
        meeting_id=None,
        speaker="Alice",
        from_value="2026-01-01",
        to_value="2026-01-04",
        filter_value="segment_count>=1",
        sort_value="started_at:desc",
        limit=10,
        max_pages=5,
        page_token=None,
        case_sensitive=False,
        json_output=True,
    )
    payload = json.loads(capsys.readouterr().out)
    assert [item["resource_id"] for item in payload["data"]["items"]] == ["t-m1", "t-m3"]
    assert payload["data"]["items"][0]["resource_type"] == "transcript"
    assert payload["data"]["items"][0]["title"] == "Alpha Sync"
    assert payload["data"]["items"][0]["snippet"] == "Alpha kickoff"
    assert payload["data"]["items"][0]["sort_key"] == "2026-01-03T10:00:00Z"
    assert payload["data"]["next_page_token"] is None
    assert client.meeting_calls == [None, "next-token"]


def test_transcript_search_with_page_token_fetches_single_page(monkeypatch, capsys) -> None:
    client = _TranscriptSearchClient()
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: client)
    transcript_commands.search_transcripts(
        query="alpha",
        meeting_id=None,
        speaker=None,
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
    assert [item["resource_id"] for item in payload["data"]["items"]] == ["t-m3"]
    assert payload["data"]["next_page_token"] is None
    assert client.meeting_calls == ["resume-token"]


def test_transcript_batch_fail_fast_stops_queue_and_marks_aborted(monkeypatch, capsys) -> None:
    client = _BatchFailFastClient()
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: client)

    tmp_dir = Path(".test_tmp") / f"transcript-batch-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        with pytest.raises(typer.Exit) as exc:
            transcript_commands.batch_transcripts(
                from_value="2026-01-01",
                to_value="2026-01-02",
                download_dir=str(tmp_dir),
                tz="UTC",
                format_value="txt",
                continue_on_error=False,
                concurrency=2,
                json_output=True,
            )
        assert exc.value.exit_code == 10
        payload = json.loads(capsys.readouterr().out)
        results = {item["meeting_id"]: item for item in payload["data"]["results"]}
        assert results["m2"]["status"] == "failed"
        assert results["m3"]["error_code"] == "FAIL_FAST_ABORTED"
        assert results["m4"]["error_code"] == "FAIL_FAST_ABORTED"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_transcript_batch_rejects_invalid_concurrency(monkeypatch) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _BatchFailFastClient())
    with pytest.raises(typer.Exit) as exc:
        transcript_commands.batch_transcripts(
            from_value="2026-01-01",
            to_value="2026-01-02",
            download_dir=str(Path(".test_tmp") / f"transcript-batch-{uuid.uuid4().hex}"),
            tz="UTC",
            format_value="txt",
            continue_on_error=True,
            concurrency=0,
            json_output=True,
        )
    assert exc.value.exit_code == 2


def test_transcript_batch_applies_adaptive_throttle(monkeypatch, capsys) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _BatchThrottleClient())
    monkeypatch.setattr(transcript_commands.time, "sleep", lambda seconds: sleeps.append(seconds))

    tmp_dir = Path(".test_tmp") / f"transcript-batch-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        transcript_commands.batch_transcripts(
            from_value="2026-01-01",
            to_value="2026-01-02",
            download_dir=str(tmp_dir),
            tz="UTC",
            format_value="txt",
            continue_on_error=True,
            concurrency=1,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert "ADAPTIVE_THROTTLE_APPLIED" in payload["warnings"]
        assert any(delay > 0 for delay in sleeps)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_transcript_batch_failed_status_is_not_terminal_in_fail_fast(monkeypatch, capsys) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _BatchFailedStatusClient())
    tmp_dir = Path(".test_tmp") / f"transcript-batch-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        transcript_commands.batch_transcripts(
            from_value="2026-01-01",
            to_value="2026-01-02",
            download_dir=str(tmp_dir),
            tz="UTC",
            format_value="txt",
            continue_on_error=False,
            concurrency=2,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        results = {item["meeting_id"]: item for item in payload["data"]["results"]}
        assert results["m2"]["status"] == "failed"
        assert "m3" in results
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_transcript_batch_builds_client_once(monkeypatch) -> None:
    build_calls = {"count": 0}

    def _build_client(token=None):
        build_calls["count"] += 1
        return _BatchFailedStatusClient()

    monkeypatch.setattr(transcript_commands, "build_client", _build_client)
    tmp_dir = Path(".test_tmp") / f"transcript-batch-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        transcript_commands.batch_transcripts(
            from_value="2026-01-01",
            to_value="2026-01-02",
            download_dir=str(tmp_dir),
            tz="UTC",
            format_value="txt",
            continue_on_error=True,
            concurrency=2,
            json_output=True,
        )
        assert build_calls["count"] == 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_transcript_batch_fail_fast_exit_code_is_deterministic_by_input_order(monkeypatch, capsys) -> None:
    monkeypatch.setattr(transcript_commands, "build_client", lambda token=None: _BatchDeterministicFailFastClient())
    tmp_dir = Path(".test_tmp") / f"transcript-batch-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        with pytest.raises(typer.Exit) as exc:
            transcript_commands.batch_transcripts(
                from_value="2026-01-01",
                to_value="2026-01-02",
                download_dir=str(tmp_dir),
                tz="UTC",
                format_value="txt",
                continue_on_error=False,
                concurrency=2,
                json_output=True,
            )
        # m1 is first in input order and maps to NO_ACCESS (exit 5).
        assert exc.value.exit_code == 5
        payload = json.loads(capsys.readouterr().out)
        results = {item["meeting_id"]: item for item in payload["data"]["results"]}
        assert results["m1"]["status"] == "failed"
        assert results["m2"]["status"] == "failed"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_parse_iso_utc_treats_naive_as_utc() -> None:
    parsed = transcript_commands._parse_iso_utc("2026-03-04T10:00:00")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.isoformat().startswith("2026-03-04T10:00:00")
