from __future__ import annotations

import os
import sys
from typing import Annotated

import typer

from webex_cli.commands.common import build_client, emit_success, fail, handle_unexpected, managed_client
from webex_cli.config.credentials import CredentialRecord, CredentialStore
from webex_cli.errors import CliError, DomainCode

auth_app = typer.Typer(help="Authenticate and manage stored Webex credentials.")


@auth_app.command("login", help="Save a Webex token and verify it has the required access.")
def login(
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            help=(
                "Webex personal access token. Disabled by default to avoid shell history exposure. "
                "Prefer WEBEX_TOKEN or --token-stdin."
            ),
        ),
    ] = None,
    token_stdin: Annotated[
        bool,
        typer.Option("--token-stdin", help="Read the token from stdin (e.g. echo $TOKEN | webex auth login --token-stdin)."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit output as a JSON envelope.")] = False,
) -> None:
    command = "auth login"
    try:
        allow_insecure_token_arg = os.environ.get("WEBEX_ALLOW_INSECURE_TOKEN_ARG") == "1"
        if token and not allow_insecure_token_arg:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Token via --token is disabled by default. Use WEBEX_TOKEN or --token-stdin. Set WEBEX_ALLOW_INSECURE_TOKEN_ARG=1 to override.",
            )
        sources: list[tuple[str, str]] = []
        if token:
            sources.append(("cli_arg", token.strip()))
        env_token = os.environ.get("WEBEX_TOKEN")
        if env_token:
            sources.append(("env", env_token.strip()))
        if token_stdin:
            stdin_token = sys.stdin.read().strip()
            if not stdin_token:
                raise CliError(DomainCode.VALIDATION_ERROR, "No token read from stdin.")
            sources.append(("stdin", stdin_token))
        if len(sources) == 0:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Provide a token via --token, WEBEX_TOKEN env var, or --token-stdin.",
            )
        distinct = {(name, value) for name, value in sources if value}
        if len(distinct) > 1:
            raise CliError(
                DomainCode.VALIDATION_ERROR,
                "Provide token from only one source at a time (--token, WEBEX_TOKEN, or --token-stdin).",
                details={"sources": [name for name, _ in sources]},
            )
        resolved_source, resolved_token = sources[0]
        if not resolved_token:
            raise CliError(DomainCode.VALIDATION_ERROR, "Token cannot be empty.")

        with managed_client(token=resolved_token, client_factory=build_client) as client:
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
                token=resolved_token,
                backend=None,
            )
        )
        warnings: list[str] = []
        if backend == "file_fallback":
            warnings.append("INSECURE_CREDENTIAL_STORE")
        if resolved_source == "cli_arg":
            warnings.append("TOKEN_CLI_ARGUMENT_INSECURE")
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


@auth_app.command("logout", help="Remove stored credentials from this machine.")
def logout(json_output: Annotated[bool, typer.Option("--json", help="Emit output as a JSON envelope.")] = False) -> None:
    command = "auth logout"
    try:
        CredentialStore().clear()
        emit_success(command, "Logged out.", as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@auth_app.command("whoami", help="Show details about the currently authenticated user.")
def whoami(json_output: Annotated[bool, typer.Option("--json", help="Emit output as a JSON envelope.")] = False) -> None:
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
