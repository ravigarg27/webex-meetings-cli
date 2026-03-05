from __future__ import annotations

from typing import Annotated

import typer

from webex_cli.commands.common import emit_success, fail, handle_unexpected, profile_scope
from webex_cli.config import ProfileStore
from webex_cli.errors import CliError

profile_app = typer.Typer(help="Manage local CLI profiles.")


@profile_app.command("create", help="Create a new local profile.")
def create_profile(
    name: str,
    default_tz: Annotated[str | None, typer.Option("--default-tz", help="Default timezone for this profile.")] = None,
    site_url: Annotated[str | None, typer.Option("--site-url", help="Optional site URL metadata (https only).")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit output as a JSON envelope.")] = False,
) -> None:
    command = "profile create"
    try:
        with profile_scope(None):
            item = ProfileStore().create_profile(name=name, default_tz=default_tz, site_url=site_url)
        emit_success(command, item, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@profile_app.command("list", help="List all local profiles.")
def list_profiles(
    json_output: Annotated[bool, typer.Option("--json", help="Emit output as a JSON envelope.")] = False,
) -> None:
    command = "profile list"
    try:
        with profile_scope(None):
            items = ProfileStore().list_profiles()
        emit_success(command, {"items": items}, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@profile_app.command("show", help="Show a profile, or the active profile when omitted.")
def show_profile(
    name: str | None = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit output as a JSON envelope.")] = False,
) -> None:
    command = "profile show"
    try:
        with profile_scope(None):
            item = ProfileStore().show_profile(name=name)
        emit_success(command, item, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@profile_app.command("use", help="Set the active local profile.")
def use_profile(
    name: str,
    json_output: Annotated[bool, typer.Option("--json", help="Emit output as a JSON envelope.")] = False,
) -> None:
    command = "profile use"
    try:
        with profile_scope(None):
            item = ProfileStore().use_profile(name)
        emit_success(command, item, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@profile_app.command("delete", help="Delete a local profile (local-only).")
def delete_profile(
    name: str,
    json_output: Annotated[bool, typer.Option("--json", help="Emit output as a JSON envelope.")] = False,
) -> None:
    command = "profile delete"
    try:
        with profile_scope(None):
            item = ProfileStore().delete_profile(name)
        emit_success(command, item, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)
