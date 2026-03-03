from __future__ import annotations

import typer

from webex_cli.commands import auth_app, meeting_app, recording_app, transcript_app

app = typer.Typer(name="webex", no_args_is_help=True)
app.add_typer(auth_app, name="auth")
app.add_typer(meeting_app, name="meeting")
app.add_typer(transcript_app, name="transcript")
app.add_typer(recording_app, name="recording")

