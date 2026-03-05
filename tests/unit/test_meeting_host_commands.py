import json
import shutil
from pathlib import Path
import uuid

import pytest
import typer

from webex_cli.commands import meeting as meeting_commands
from webex_cli.runtime import use_non_interactive


class _HostClient:
    def __init__(self) -> None:
        self.create_calls: list[dict] = []
        self.update_calls: list[tuple[str, dict]] = []
        self.cancel_calls: list[tuple[str, bool, str | None]] = []
        self.invitee_add_calls: list[tuple[str, list[str]]] = []

    def create_meeting(self, payload: dict, *, idempotency_key: str | None = None):
        self.create_calls.append({"payload": payload, "idempotency_key": idempotency_key})
        return {"id": "m-created", "title": payload["title"], "start": payload["start"], "end": payload["end"]}

    def update_meeting(self, meeting_id: str, payload: dict, *, idempotency_key: str | None = None):
        self.update_calls.append((meeting_id, {"payload": payload, "idempotency_key": idempotency_key}))
        return {"id": meeting_id, **payload}

    def cancel_meeting(self, meeting_id: str, *, notify: bool, reason: str | None, idempotency_key: str | None = None):
        self.cancel_calls.append((meeting_id, notify, reason))
        return {"meeting_id": meeting_id, "cancelled": True}

    def list_invitees(self, meeting_id: str):
        return [{"email": "one@example.test"}, {"email": "two@example.test"}]

    def add_invitees(self, meeting_id: str, invitees: list[str], *, idempotency_key: str | None = None):
        self.invitee_add_calls.append((meeting_id, invitees))
        return {"meeting_id": meeting_id, "added": invitees}

    def remove_invitees(self, meeting_id: str, invitees: list[str], *, idempotency_key: str | None = None):
        return {"meeting_id": meeting_id, "removed": invitees}

    def probe_templates_access(self):
        raise NotImplementedError

    def list_meeting_templates(self):
        return [{"template_id": "t1", "name": "Team Sync"}]

    def apply_template(self, template_id: str, payload: dict, *, idempotency_key: str | None = None):
        return {"id": "m-from-template", "template_id": template_id, **payload}

    def probe_recurrence_access(self):
        return None

    def create_recurrence(self, payload: dict, *, idempotency_key: str | None = None):
        return {"series_id": "series-1", **payload}

    def update_recurrence(self, series_id: str, payload: dict, *, idempotency_key: str | None = None):
        return {"series_id": series_id, **payload}

    def cancel_recurrence(self, series_id: str, *, from_occurrence: str | None, idempotency_key: str | None = None):
        return {"series_id": series_id, "from_occurrence": from_occurrence, "cancelled": True}


class _TemplateCapabilityMissingClient(_HostClient):
    def probe_templates_access(self):
        return False


def _temp_root() -> Path:
    root = Path(".test_tmp") / f"meeting-host-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_meeting_create_dry_run_returns_mutation_contract(monkeypatch, capsys) -> None:
    client = _HostClient()
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: client)
    meeting_commands.create_meeting(
        title="Team Sync",
        start="2026-01-10T10:00:00Z",
        end="2026-01-10T11:00:00Z",
        timezone=None,
        agenda=None,
        template_id=None,
        invitees=None,
        invitees_file=None,
        invitees_file_format="lines",
        dry_run=True,
        idempotency_key=None,
        idempotency_auto=True,
        json_output=True,
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["state"] == "dry_run_validated"
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["dry_run_mode"] == "local_validation"
    assert payload["data"]["idempotency_key"]
    assert client.create_calls == []


def test_meeting_cancel_requires_confirmation_in_non_interactive_mode(monkeypatch) -> None:
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: _HostClient())
    with use_non_interactive(True):
        with pytest.raises(typer.Exit) as exc:
            meeting_commands.cancel_meeting(
                meeting_id="m1",
                reason=None,
                notify=True,
                confirm=False,
                yes=False,
                idempotency_key="cancel-1",
                idempotency_auto=False,
                json_output=True,
            )
    assert exc.value.exit_code == 2


def test_meeting_create_idempotent_replay_returns_no_op(monkeypatch, capsys) -> None:
    client = _HostClient()
    root = _temp_root()
    try:
        monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: client)
        monkeypatch.setenv("APPDATA", str(root))
        meeting_commands.create_meeting(
            title="Planning",
            start="2026-01-10T10:00:00Z",
            end="2026-01-10T11:00:00Z",
            timezone=None,
            agenda=None,
            template_id=None,
            invitees=None,
            invitees_file=None,
            invitees_file_format="lines",
            dry_run=False,
            idempotency_key="meeting-create-1",
            idempotency_auto=False,
            json_output=True,
        )
        first = json.loads(capsys.readouterr().out)
        meeting_commands.create_meeting(
            title="Planning",
            start="2026-01-10T10:00:00Z",
            end="2026-01-10T11:00:00Z",
            timezone=None,
            agenda=None,
            template_id=None,
            invitees=None,
            invitees_file=None,
            invitees_file_format="lines",
            dry_run=False,
            idempotency_key="meeting-create-1",
            idempotency_auto=False,
            json_output=True,
        )
        second = json.loads(capsys.readouterr().out)
        assert first["data"]["state"] == "completed"
        assert second["data"]["state"] == "no_op"
        assert len(client.create_calls) == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_invitee_add_supports_csv_files(monkeypatch, capsys) -> None:
    client = _HostClient()
    root = _temp_root()
    csv_path = root / "invitees.csv"
    csv_path.write_text("email\none@example.test\ntwo@example.test\n", encoding="utf-8")
    try:
        monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: client)
        meeting_commands.add_invitees(
            meeting_id="m1",
            invitees=None,
            invitees_file=str(csv_path),
            invitees_file_format="csv",
            idempotency_key="invitee-add-1",
            idempotency_auto=False,
            json_output=True,
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["data"]["state"] == "completed"
        assert client.invitee_add_calls == [("m1", ["one@example.test", "two@example.test"])]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_invitee_add_rejects_unsupported_file_format(monkeypatch) -> None:
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: _HostClient())
    with pytest.raises(typer.Exit) as exc:
        meeting_commands.add_invitees(
            meeting_id="m1",
            invitees=None,
            invitees_file="invitees.txt",
            invitees_file_format="tsv",
            idempotency_key="invitee-add-2",
            idempotency_auto=False,
            json_output=True,
        )
    assert exc.value.exit_code == 2


def test_template_list_returns_capability_error(monkeypatch) -> None:
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: _TemplateCapabilityMissingClient())
    with pytest.raises(typer.Exit) as exc:
        meeting_commands.list_templates(json_output=True)
    assert exc.value.exit_code == 5


def test_recurrence_create_rejects_unsupported_rrule_keys(monkeypatch) -> None:
    monkeypatch.setattr(meeting_commands, "build_client", lambda token=None: _HostClient())
    with pytest.raises(typer.Exit) as exc:
        meeting_commands.create_recurrence(
            title="Series",
            rrule="FREQ=WEEKLY;BYSECOND=10",
            start="2026-01-10T10:00:00Z",
            duration=30,
            invitees=None,
            invitees_file=None,
            invitees_file_format="lines",
            dry_run=True,
            idempotency_key=None,
            idempotency_auto=True,
            json_output=True,
        )
    assert exc.value.exit_code == 2
