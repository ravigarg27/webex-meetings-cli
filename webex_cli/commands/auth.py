from __future__ import annotations

import typer

from webex_cli.commands.common import emit_success

auth_app = typer.Typer(help="Authentication commands")


@auth_app.command("login")
def login(token: str = typer.Option(..., "--token", help="Webex token")) -> None:
    emit_success("auth login", {"status": "not_implemented", "token_supplied": bool(token)}, as_json=False)


@auth_app.command("logout")
def logout() -> None:
    emit_success("auth logout", {"status": "not_implemented"}, as_json=False)


@auth_app.command("whoami")
def whoami(json_output: bool = typer.Option(False, "--json")) -> None:
    emit_success("auth whoami", {"status": "not_implemented"}, as_json=json_output)

