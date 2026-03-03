from __future__ import annotations

import os
import sys

import typer

from webex_cli.commands.common import build_client, emit_success, fail, handle_unexpected, managed_client
from webex_cli.config.credentials import CredentialRecord, CredentialStore
from webex_cli.errors import CliError, DomainCode

auth_app = typer.Typer(help="Authentication commands")


def _bool_option(value: bool | object) -> bool:
    return value if isinstance(value, bool) else False


@auth_app.command("login")
def login(
    token: str | None = typer.Option(None, "--token", help="Webex token (less secure; prefer WEBEX_TOKEN or --token-stdin)"),
    token_stdin: bool = typer.Option(False, "--token-stdin", help="Read Webex token from stdin."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    command = "auth login"
    json_mode = _bool_option(json_output)
    read_stdin = _bool_option(token_stdin)
    try:
        sources: list[tuple[str, str]] = []
        if token:
            sources.append(("cli_arg", token.strip()))
        env_token = os.environ.get("WEBEX_TOKEN")
        if env_token:
            sources.append(("env", env_token.strip()))
        if read_stdin:
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
            as_json=json_mode,
            warnings=warnings,
        )
    except CliError as exc:
        fail(command, exc, as_json=json_mode)
    except Exception as exc:
        handle_unexpected(command, as_json=json_mode, exc=exc)


@auth_app.command("logout")
def logout(json_output: bool = typer.Option(False, "--json")) -> None:
    command = "auth logout"
    json_mode = _bool_option(json_output)
    try:
        CredentialStore().clear()
        emit_success(command, {"status": "logged_out"}, as_json=json_mode)
    except CliError as exc:
        fail(command, exc, as_json=json_mode)
    except Exception as exc:
        handle_unexpected(command, as_json=json_mode, exc=exc)


@auth_app.command("whoami")
def whoami(json_output: bool = typer.Option(False, "--json")) -> None:
    command = "auth whoami"
    json_mode = _bool_option(json_output)
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
        emit_success(command, data, as_json=json_mode, warnings=warnings)
    except CliError as exc:
        fail(command, exc, as_json=json_mode)
    except Exception as exc:
        handle_unexpected(command, as_json=json_mode, exc=exc)
