from __future__ import annotations

import typer

from webex_cli.commands.common import build_client, emit_success, fail, handle_unexpected, managed_client
from webex_cli.config.credentials import CredentialRecord, CredentialStore
from webex_cli.errors import CliError, DomainCode

auth_app = typer.Typer(help="Authentication commands")


@auth_app.command("login")
def login(
    token: str = typer.Option(..., "--token", help="Webex token"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    command = "auth login"
    try:
        with managed_client(token=token, client_factory=build_client) as client:
            who = client.whoami()
            try:
                client.probe_meetings_access()
            except CliError as exc:
                if exc.code in {DomainCode.AUTH_INVALID, DomainCode.NO_ACCESS}:
                    raise CliError(
                        DomainCode.AUTH_INVALID,
                        "Token does not have required participant-meetings access.",
                        details=exc.details,
                    ) from exc
                raise
        store = CredentialStore()
        backend = store.save(
            CredentialRecord(
                token=token,
                user_id=who.get("user_id"),
                display_name=who.get("display_name"),
                primary_email=who.get("primary_email"),
                org_id=who.get("org_id"),
                site_url=who.get("site_url"),
                backend=None,
            )
        )
        warnings: list[str] = []
        if backend == "file_fallback":
            warnings.append("INSECURE_CREDENTIAL_STORE")
        emit_success(
            command,
            {
                "user_id": who.get("user_id"),
                "display_name": who.get("display_name"),
                "primary_email": who.get("primary_email"),
                "org_id": who.get("org_id"),
                "site_url": who.get("site_url"),
                "token_state": "valid",
                "credential_backend": backend,
            },
            as_json=json_output,
            warnings=warnings,
        )
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@auth_app.command("logout")
def logout(json_output: bool = typer.Option(False, "--json")) -> None:
    command = "auth logout"
    try:
        CredentialStore().clear()
        emit_success(command, {"status": "logged_out"}, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@auth_app.command("whoami")
def whoami(json_output: bool = typer.Option(False, "--json")) -> None:
    command = "auth whoami"
    try:
        record = CredentialStore().load()
        with managed_client(token=record.token, client_factory=build_client) as client:
            who = client.whoami()
        warnings: list[str] = []
        if record.backend == "file_fallback":
            warnings.append("INSECURE_CREDENTIAL_STORE")
        data = {
            "user_id": who.get("user_id"),
            "display_name": who.get("display_name"),
            "primary_email": who.get("primary_email"),
            "org_id": who.get("org_id"),
            "site_url": who.get("site_url"),
            "token_state": who.get("token_state", "valid"),
            "credential_backend": record.backend,
        }
        emit_success(command, data, as_json=json_output, warnings=warnings)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)
