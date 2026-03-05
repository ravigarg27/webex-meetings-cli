from __future__ import annotations

from contextlib import nullcontext
import os
import sys
from typing import Annotated

import typer

from webex_cli.commands.common import (
    build_client,
    emit_success,
    fail,
    handle_unexpected,
    managed_client,
    load_credential_record,
    profile_scope,
    resolve_profile,
)
from webex_cli.config.credentials import CredentialRecord, CredentialStore
from webex_cli.errors import CliError, DomainCode
from webex_cli.oauth import (
    OAuthDeviceConfig,
    OAuthTokenBundle,
    poll_for_device_token,
    resolve_oauth_device_config,
    start_device_authorization,
)
from webex_cli.runtime import get_non_interactive, use_non_interactive

auth_app = typer.Typer(help="Authenticate and manage stored Webex credentials.")


def _auth_cause(details: dict[str, object] | None) -> str:
    upstream_code = str((details or {}).get("upstream_code") or "").strip().lower()
    if upstream_code in {"token_expired", "expired_token"}:
        return "expired"
    if upstream_code in {"revoked_token", "token_revoked", "invalid_grant"}:
        return "revoked"
    if upstream_code in {"insufficient_scope", "missing_scope"}:
        return "insufficient_scope"
    return "invalid"


def _validate_pat_sources(
    *,
    token: str | None,
    token_stdin: bool,
) -> tuple[str, str]:
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
    return resolved_source, resolved_token


def _verify_token_access(token_value: str) -> dict[str, object]:
    with managed_client(token=token_value, client_factory=build_client) as client:
        who = client.whoami()
        try:
            client.probe_meetings_access()
        except CliError as exc:
            if exc.code in {DomainCode.AUTH_INVALID, DomainCode.NO_ACCESS}:
                raise CliError(
                    DomainCode.AUTH_INVALID,
                    "Token does not have required participant-meetings access.",
                    details={"auth_cause": _auth_cause(exc.details), **(exc.details or {})},
                ) from exc
            raise
    return who


def _save_pat_profile(profile_key: str, token_value: str) -> tuple[str, list[str]]:
    store = CredentialStore(profile=profile_key)
    backend = store.save(
        CredentialRecord(
            token=token_value,
            backend=None,
            auth_type="pat",
            refresh_token=None,
            expires_at=None,
            scopes=[],
            invalid_reason=None,
        )
    )
    warnings: list[str] = []
    if backend == "file_fallback":
        warnings.append("INSECURE_CREDENTIAL_STORE")
    return backend, warnings


def _save_oauth_profile(profile_key: str, bundle: OAuthTokenBundle, config: OAuthDeviceConfig) -> tuple[str, list[str]]:
    store = CredentialStore(profile=profile_key)
    backend = store.save(
        CredentialRecord(
            token=bundle.access_token,
            backend=None,
            auth_type="oauth",
            refresh_token=bundle.refresh_token,
            expires_at=bundle.expires_at,
            scopes=bundle.scopes,
            invalid_reason=None,
            oauth_client_id=config.client_id,
            oauth_device_authorize_url=config.device_authorize_url,
            oauth_token_url=config.token_url,
            oauth_scope=config.scope,
            oauth_poll_interval_seconds=config.poll_interval_seconds,
            oauth_timeout_seconds=config.timeout_seconds,
        )
    )
    warnings: list[str] = []
    if backend == "file_fallback":
        warnings.append("INSECURE_CREDENTIAL_STORE")
    if bundle.refresh_token and store.load().refresh_token is None:
        warnings.append("REFRESH_TOKEN_NOT_PERSISTED")
    return backend, warnings


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
    oauth_device_flow: Annotated[
        bool,
        typer.Option("--oauth-device-flow", help="Use OAuth device flow instead of a PAT."),
    ] = False,
    oauth_client_id: Annotated[str | None, typer.Option("--oauth-client-id", help="OAuth client_id override.")] = None,
    oauth_device_authorize_url: Annotated[
        str | None,
        typer.Option("--oauth-device-authorize-url", help="OAuth device authorization endpoint override."),
    ] = None,
    oauth_token_url: Annotated[
        str | None,
        typer.Option("--oauth-token-url", help="OAuth token endpoint override."),
    ] = None,
    oauth_scope: Annotated[str | None, typer.Option("--oauth-scope", help="OAuth scope string override.")] = None,
    oauth_poll_interval: Annotated[
        int | None,
        typer.Option("--oauth-poll-interval", help="OAuth polling interval in seconds (2-30)."),
    ] = None,
    oauth_timeout: Annotated[
        int | None,
        typer.Option("--oauth-timeout", help="OAuth device flow timeout in seconds."),
    ] = None,
    non_interactive: Annotated[
        bool,
        typer.Option(
            "--non-interactive",
            help="Disable interactive OAuth prompts. Device flow exits immediately when this flag is set.",
            hidden=True,
        ),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit output as a JSON envelope.")] = False,
) -> None:
    command = "auth login"
    non_interactive_mode = non_interactive or get_non_interactive()
    non_interactive_scope = use_non_interactive(non_interactive_mode) if non_interactive_mode else nullcontext()
    try:
        with profile_scope(None), non_interactive_scope:
            profile_key = resolve_profile()
            has_pat_source = bool(token or os.environ.get("WEBEX_TOKEN") or token_stdin)
            if oauth_device_flow and has_pat_source:
                raise CliError(
                    DomainCode.VALIDATION_ERROR,
                    "PAT inputs and --oauth-device-flow are mutually exclusive.",
                )

            auth_method = "pat"
            warnings: list[str]
            who: dict[str, object]
            backend: str
            expires_at: str | None = None
            scopes: list[str] = []
            if oauth_device_flow:
                auth_method = "oauth_device_flow"
                if non_interactive_mode:
                    raise CliError(
                        DomainCode.VALIDATION_ERROR,
                        "OAuth device flow cannot run in non-interactive mode.",
                    )
                config = resolve_oauth_device_config(
                    client_id=oauth_client_id,
                    device_authorize_url=oauth_device_authorize_url,
                    token_url=oauth_token_url,
                    scope=oauth_scope,
                    poll_interval_seconds=oauth_poll_interval,
                    timeout_seconds=oauth_timeout,
                )
                device = start_device_authorization(config)
                if not json_output:
                    verification_uri = device.get("verification_uri_complete") or device.get("verification_uri")
                    typer.echo("Open this URL and complete authorization:", err=True)
                    typer.echo(str(verification_uri), err=True)
                    typer.echo(f"User code: {device.get('user_code')}", err=True)
                bundle = poll_for_device_token(
                    config,
                    device_code=str(device["device_code"]),
                    interval_seconds=int(device["interval_seconds"]),
                )
                who = _verify_token_access(bundle.access_token)
                backend, warnings = _save_oauth_profile(profile_key, bundle, config)
                expires_at = bundle.expires_at
                scopes = bundle.scopes
            else:
                resolved_source, resolved_token = _validate_pat_sources(token=token, token_stdin=token_stdin)
                who = _verify_token_access(resolved_token)
                backend, warnings = _save_pat_profile(profile_key, resolved_token)
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
                    "profile": profile_key,
                    "auth_method": auth_method,
                    "expires_at": expires_at,
                    "scopes": scopes,
                },
                as_json=json_output,
                warnings=warnings,
            )
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@auth_app.command("logout", help="Remove stored credentials from this machine.")
def logout(
    json_output: Annotated[bool, typer.Option("--json", help="Emit output as a JSON envelope.")] = False,
) -> None:
    command = "auth logout"
    try:
        with profile_scope(None):
            profile_key = resolve_profile()
            CredentialStore(profile=profile_key).clear()
            emit_success(command, {"message": "Logged out.", "profile": profile_key}, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@auth_app.command("whoami", help="Show details about the currently authenticated user.")
def whoami(
    json_output: Annotated[bool, typer.Option("--json", help="Emit output as a JSON envelope.")] = False,
) -> None:
    command = "auth whoami"
    try:
        with profile_scope(None):
            profile_key = resolve_profile()
            record = load_credential_record()
            with managed_client(client_factory=build_client) as client:
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
                "profile": profile_key,
                "auth_method": record.auth_type,
                "expires_at": record.expires_at,
                "scopes": record.scopes or [],
            }
            emit_success(command, data, as_json=json_output, warnings=warnings)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)
