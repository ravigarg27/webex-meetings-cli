import json

import pytest
import typer

from webex_cli.commands import meeting as meeting_commands


class _PagedMeetingClient:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def list_meetings(self, *, from_utc, to_utc, page_size, page_token, host_email=None):
        self.calls.append(page_token)
        if page_token is None:
            return (
                [
                    {
                        "id": "m1",
                        "title": "First",
                        "start": "2026-01-02T10:00:00Z",
                        "end": "2026-01-02T11:00:00Z",
                        "hasTranscription": True,
                        "hasRecording": False,
                    }
                ],
                "t1",
            )
        return (
            [
                {
                    "id": "m2",
                    "title": "Second",
                    "start": "2026-01-01T10:00:00Z",
                    "end": "2026-01-01T11:00:00Z",
                    "hasTranscription": False,
                    "hasRecording": True,
                }
            ],
            None,
        )


class _SinglePageMeetingClient:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def list_meetings(self, *, from_utc, to_utc, page_size, page_token, host_email=None):
        self.calls.append(page_token)
        return (
            [
                {
                    "id": "m3",
                    "title": "Single Page",
                    "start": "2026-01-03T10:00:00Z",
                    "end": "2026-01-03T11:00:00Z",
                    "hasTranscription": False,
                    "hasRecording": False,
                }
            ],
            "next-token",
        )


class _MeetingDetailClient:
    def get_meeting(self, meeting_id):
        return {
            "id": meeting_id,
            "title": "Detail Meeting",
            "start": "2026-01-03T10:00:00Z",
            "end": "2026-01-03T11:00:00Z",
            "webLink": "https://example.test/join",
            "hasTranscription": True,
            "hasRecording": True,
            "hostEmail": "host@example.test",
        }


class _MeetingSearchClient:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def list_meetings(self, *, from_utc, to_utc, page_size, page_token, host_email=None):
        self.calls.append(page_token)
        if page_token is None:
            return (
                [
                    {
                        "id": "m1",
                        "title": "Alpha Review",
                        "start": "2026-01-03T10:00:00Z",
                        "hostEmail": "a@example.test",
                        "hasTranscription": True,
                        "hasRecording": False,
                    },
                    {
                        "id": "m2",
                        "title": "Beta Sync",
                        "start": "2026-01-02T10:00:00Z",
                        "hostEmail": "b@example.test",
                        "hasTranscription": False,
                        "hasRecording": True,
                    },
                ],
                "next-token",
            )
        return (
            [
                {
                    "id": "m3",
                    "title": "alpha wrap",
                    "start": "2026-01-01T10:00:00Z",
                    "hostEmail": "c@example.test",
                    "hasTranscription": False,
                    "hasRecording": True,
                }
            ],
            None,
        )


def test_meeting_list_autofetches_all_pages(monkeypatch, capsys) -> None:
    client = _PagedMeetingClient()
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: client)
    meeting_commands.list_meetings(
        from_value="2026-01-01",
        to_value="2026-01-03",
        last=None,
        tz="UTC",
        page_size=50,
        page_token=None,
        json_output=True,
    )
    output = json.loads(capsys.readouterr().out)
    assert len(output["data"]["items"]) == 2
    assert output["data"]["next_page_token"] is None
    assert client.calls == [None, "t1"]


def test_meeting_list_with_page_token_returns_single_page_and_next_token(monkeypatch, capsys) -> None:
    client = _SinglePageMeetingClient()
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: client)
    meeting_commands.list_meetings(
        from_value="2026-01-01",
        to_value="2026-01-04",
        last=None,
        tz="UTC",
        page_size=10,
        page_token="resume-token",
        json_output=True,
    )
    output = json.loads(capsys.readouterr().out)
    assert len(output["data"]["items"]) == 1
    assert output["data"]["items"][0]["meeting_id"] == "m3"
    assert output["data"]["next_page_token"] == "next-token"
    assert client.calls == ["resume-token"]


def test_meeting_list_last_truncates_results(monkeypatch, capsys) -> None:
    client = _PagedMeetingClient()
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: client)
    meeting_commands.list_meetings(
        from_value=None,
        to_value=None,
        last=1,
        tz="UTC",
        page_size=50,
        page_token=None,
        json_output=True,
    )
    output = json.loads(capsys.readouterr().out)
    assert len(output["data"]["items"]) == 1
    assert output["data"]["items"][0]["meeting_id"] == "m1"


def test_meeting_list_last_rejects_zero(monkeypatch) -> None:
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: _PagedMeetingClient())
    with pytest.raises(typer.Exit) as exc:
        meeting_commands.list_meetings(
            from_value=None, to_value=None, last=0,
            tz="UTC", page_size=50, page_token=None, json_output=True,
        )
    assert exc.value.exit_code != 0


def test_meeting_list_last_conflicts_with_from_to(monkeypatch) -> None:
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: _PagedMeetingClient())
    with pytest.raises(typer.Exit) as exc:
        meeting_commands.list_meetings(
            from_value="2026-01-01", to_value="2026-01-02", last=5,
            tz="UTC", page_size=50, page_token=None, json_output=True,
        )
    assert exc.value.exit_code != 0


def test_meeting_list_maps_has_transcript_and_has_recording(monkeypatch, capsys) -> None:
    client = _PagedMeetingClient()
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: client)
    meeting_commands.list_meetings(
        from_value="2026-01-01",
        to_value="2026-01-03",
        last=None,
        tz="UTC",
        page_size=50,
        page_token=None,
        json_output=True,
    )
    output = json.loads(capsys.readouterr().out)
    items = {i["meeting_id"]: i for i in output["data"]["items"]}
    assert items["m1"]["has_transcript"] is True
    assert items["m1"]["has_recording"] is False
    assert items["m2"]["has_transcript"] is False
    assert items["m2"]["has_recording"] is True


def test_meeting_get_normalizes_response(monkeypatch, capsys) -> None:
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: _MeetingDetailClient())
    meeting_commands.get_meeting(meeting_id="m1", json_output=True)
    payload = json.loads(capsys.readouterr().out)
    data = payload["data"]
    assert data["meeting_id"] == "m1"
    assert data["join_url"] == "https://example.test/join"
    assert data["transcript_hint"] is True
    assert data["recording_hint"] is True


def test_meeting_search_applies_query_filter_sort_and_contract(monkeypatch, capsys) -> None:
    client = _MeetingSearchClient()
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: client)
    meeting_commands.search_meetings(
        query="alpha",
        from_value="2026-01-01",
        to_value="2026-01-04",
        filter_value="has_transcript=true OR meeting_id='m3'",
        sort_value="started_at:desc",
        limit=10,
        max_pages=5,
        page_token=None,
        case_sensitive=False,
        json_output=True,
    )
    payload = json.loads(capsys.readouterr().out)
    assert [item["resource_id"] for item in payload["data"]["items"]] == ["m1", "m3"]
    assert payload["data"]["items"][0]["resource_type"] == "meeting"
    assert payload["data"]["items"][0]["title"] == "Alpha Review"
    assert payload["data"]["items"][0]["snippet"] == "Alpha Review"
    assert payload["data"]["items"][0]["sort_key"] == "2026-01-03T10:00:00Z"
    assert payload["data"]["next_page_token"] is None
    assert client.calls == [None, "next-token"]


def test_meeting_search_with_page_token_fetches_single_page(monkeypatch, capsys) -> None:
    client = _MeetingSearchClient()
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: client)
    meeting_commands.search_meetings(
        query="alpha",
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
    assert [item["resource_id"] for item in payload["data"]["items"]] == ["m3"]
    assert payload["data"]["next_page_token"] is None
    assert client.calls == ["resume-token"]
