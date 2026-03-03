from __future__ import annotations

import typer

from webex_cli.commands import auth_app, meeting_app, recording_app, transcript_app
from webex_cli.version import __version__

app = typer.Typer(name="webex", no_args_is_help=True)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show CLI version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    _ = version


app.add_typer(auth_app, name="auth")
app.add_typer(meeting_app, name="meeting")
app.add_typer(transcript_app, name="transcript")
app.add_typer(recording_app, name="recording")
