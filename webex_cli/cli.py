from __future__ import annotations

import os

import typer

from webex_cli.commands import auth_app, event_app, meeting_app, profile_app, recording_app, transcript_app
from webex_cli.runtime import (
    reset_current_profile,
    reset_log_format,
    reset_non_interactive,
    reset_request_id_override,
    set_current_profile,
    set_log_format,
    set_non_interactive,
    set_request_id_override,
)
from webex_cli.utils.logging import configure_logging
from webex_cli.version import __version__

app = typer.Typer(name="webex", no_args_is_help=True)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Show CLI version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Use a specific local profile for this command.",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Disable interactive prompts for this command.",
    ),
    request_id: str | None = typer.Option(
        None,
        "--request-id",
        help="Optional correlation ID for logs and JSON output metadata.",
    ),
    log_format: str | None = typer.Option(
        None,
        "--log-format",
        help="Log format for diagnostics: text or json. Defaults to WEBEX_LOG_FORMAT or text.",
    ),
) -> None:
    _ = version
    resolved_log_format = (log_format or os.environ.get("WEBEX_LOG_FORMAT") or "text").strip().lower()
    if resolved_log_format not in {"text", "json"}:
        raise typer.BadParameter("--log-format must be one of: text, json.")
    configure_logging(resolved_log_format)
    log_format_token = set_log_format(resolved_log_format)
    request_id_override_token = set_request_id_override(request_id)
    profile_token = set_current_profile(profile)
    non_interactive_token = set_non_interactive(non_interactive)

    def _reset_runtime() -> None:
        reset_non_interactive(non_interactive_token)
        reset_current_profile(profile_token)
        reset_request_id_override(request_id_override_token)
        reset_log_format(log_format_token)

    ctx.call_on_close(_reset_runtime)


app.add_typer(auth_app, name="auth")
app.add_typer(event_app, name="event")
app.add_typer(meeting_app, name="meeting")
app.add_typer(profile_app, name="profile")
app.add_typer(transcript_app, name="transcript")
app.add_typer(recording_app, name="recording")
