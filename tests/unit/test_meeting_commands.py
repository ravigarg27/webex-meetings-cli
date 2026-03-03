import json

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
        tz="UTC",
        page_size=50,
        page_token=None,
        json_output=True,
    )
    output = json.loads(capsys.readouterr().out)
    assert len(output["data"]["items"]) == 2
    assert output["data"]["next_page_token"] is None
    assert client.calls == [None, "t1"]
