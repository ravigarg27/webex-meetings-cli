from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import typer

from webex_cli.capabilities import capability_unavailable, probe_capability
from webex_cli.commands.common import (
    build_client,
    emit_success,
    fail,
    fetch_all_pages,
    handle_unexpected,
    managed_client,
    profile_scope,
    resolve_effective_timezone,
    resolve_profile,
    validate_id,
)
from webex_cli.host_utils import parse_invitees, validate_rrule
from webex_cli.errors import CliError, DomainCode
from webex_cli.mutations import MutationResponse, require_confirmation, resolve_idempotency_key, run_mutation
from webex_cli.search import collect_pages, evaluate_filter, match_query, primary_sort_field, sort_items
from webex_cli.utils.time import parse_time_range

meeting_app = typer.Typer(help="List and inspect Webex meetings.")
invitee_app = typer.Typer(help="Manage meeting invitees.")
template_app = typer.Typer(help="Manage meeting templates.")
recurrence_app = typer.Typer(help="Manage recurring meeting series.")

DEFAULT_LAST_LOOKBACK_DAYS = 30
DEFAULT_SEARCH_LIMIT = 50
DEFAULT_SEARCH_MAX_PAGES = 5
SEARCH_PAGE_SIZE = 200
MEETING_SEARCH_SCHEMA = {
    "meeting_id": "string",
    "title": "string",
    "started_at": "datetime",
    "host_email": "string",
    "host_name": "string",
    "has_transcript": "bool",
    "has_recording": "bool",
    "score": "int",
}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _meeting_duration(item: dict[str, Any]) -> str:
    started = _parse_dt(item.get("start") or item.get("startedAt") or item.get("started_at"))
    ended = _parse_dt(item.get("end") or item.get("endedAt") or item.get("ended_at"))
    if not started or not ended:
        return ""
    minutes = int((ended - started).total_seconds() // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m" if mins else f"{hours}h"


def _normalize_meeting(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "meeting_id": item.get("id") or item.get("meetingId"),
        "title": item.get("title") or item.get("topic") or "",
        "started_at": item.get("start") or item.get("startedAt") or item.get("started_at"),
        "duration": _meeting_duration(item),
        "host_email": item.get("hostEmail") or item.get("host_email"),
        "host_name": item.get("hostDisplayName"),
        "has_transcript": item.get("hasTranscription") or False,
        "has_recording": item.get("hasRecording") or False,
    }


def _normalize_meeting_detail(item: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_meeting(item)
    join_url = item.get("webLink") or item.get("joinWebUrl") or item.get("joinUrl")
    normalized["join_url"] = join_url
    normalized["transcript_hint"] = bool(item.get("hasTranscription") or item.get("hasTranscript"))
    normalized["recording_hint"] = bool(item.get("hasRecording"))
    return normalized


def _resolve_search_window(from_value: str | None, to_value: str | None, tz: object | None) -> tuple[str, str]:
    if not isinstance(from_value, str):
        from_value = None
    if not isinstance(to_value, str):
        to_value = None
    now = datetime.now(timezone.utc)
    if from_value is None:
        from_value = (now - timedelta(days=DEFAULT_LAST_LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if to_value is None:
        to_value = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    effective_tz = tz if isinstance(tz, str) else None
    return parse_time_range(from_value, to_value, resolve_effective_timezone(effective_tz))


def _meeting_search_text(item: dict[str, Any]) -> list[object]:
    return [
        item.get("title"),
        item.get("host_email"),
        item.get("host_name"),
        item.get("meeting_id"),
    ]


def _meeting_search_result(item: dict[str, Any], *, snippet: str, score: int, sort_field: str) -> dict[str, Any]:
    return {
        "resource_type": "meeting",
        "resource_id": item.get("meeting_id"),
        "title": item.get("title") or "",
        "snippet": snippet,
        "score": score,
        "sort_key": item.get(sort_field),
    }


def _parse_host_datetime(value: str, field_name: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise CliError(DomainCode.VALIDATION_ERROR, f"Invalid {field_name} datetime.", details={field_name: value}) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_start_end(start: str, end: str) -> tuple[str, str]:
    normalized_start = _parse_host_datetime(start, "start")
    normalized_end = _parse_host_datetime(end, "end")
    if normalized_start >= normalized_end:
        raise CliError(DomainCode.VALIDATION_ERROR, "`--end` must be later than `--start`.")
    return normalized_start, normalized_end


def _require_non_empty_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise CliError(
            DomainCode.VALIDATION_ERROR,
            f"`{field_name}` must not be empty.",
            details={field_name.lstrip('-').replace('-', '_'): value},
        )
    return normalized


def _confirm_destructive(command_label: str, confirm: bool, yes: bool) -> None:
    require_confirmation(confirm, yes, command_label=command_label)
    if confirm or yes:
        return
    if not typer.confirm(f"Proceed with {command_label}?"):
        raise CliError(DomainCode.VALIDATION_ERROR, "Operation cancelled by user.")


def _capability_probe(client: Any, probe_name: str) -> bool:
    method = getattr(client, probe_name, None)
    if not callable(method):
        return False
    try:
        result = method()
        if isinstance(result, bool):
            return result
        return True
    except CliError as exc:
        if exc.code in {DomainCode.NOT_FOUND, DomainCode.NO_ACCESS, DomainCode.VALIDATION_ERROR, DomainCode.CAPABILITY_ERROR}:
            return False
        raise


def _require_capability(
    client: Any,
    *,
    feature: str,
    probe_name: str,
    error_code: str,
    message: str,
    fallback_command: str,
    fallback_methods: tuple[str, ...] = (),
) -> None:
    probe = getattr(client, probe_name, None)
    profile_key = resolve_profile()
    result = probe_capability(
        feature,
        profile=profile_key,
        probe_fn=lambda: (
            _capability_probe(client, probe_name)
            if callable(probe)
            else all(callable(getattr(client, method_name, None)) for method_name in fallback_methods)
        ),
    )
    if not result.available:
        raise capability_unavailable(error_code, message, details={"fallback_command": fallback_command})


def _emit_mutation(command: str, response: MutationResponse, *, as_json: bool) -> None:
    emit_success(command, response.payload, as_json=as_json, warnings=response.warnings)


def _execute_mutation(
    *,
    profile: str,
    command: str,
    payload: dict[str, Any],
    dry_run: bool,
    idempotency_key: str,
    validation: dict[str, Any],
    execute: Any,
) -> MutationResponse:
    if dry_run:
        return run_mutation(
            profile=profile,
            command=command,
            payload=payload,
            dry_run=True,
            idempotency_key=idempotency_key,
            validation=validation,
            execute=lambda _key: {},
        )
    return execute()


def _create_meeting_with_client(payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
    with managed_client(client_factory=build_client) as client:
        return client.create_meeting(payload, idempotency_key=idempotency_key)


def _update_meeting_with_client(meeting_id: str, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
    with managed_client(client_factory=build_client) as client:
        return client.update_meeting(meeting_id, payload, idempotency_key=idempotency_key)


def _apply_template_mutation(
    *,
    template_id: str,
    payload: dict[str, Any],
    profile_key: str,
    command: str,
    mutation_payload: dict[str, Any],
    idempotency_key: str,
    validation: dict[str, Any],
) -> MutationResponse:
    with managed_client(client_factory=build_client) as client:
        _require_capability(
            client,
            feature="templates",
            probe_name="probe_templates_access",
            error_code="TEMPLATE_CAPABILITY_UNAVAILABLE",
            message="Templates are unavailable for this account.",
            fallback_command="webex meeting create",
            fallback_methods=("apply_template",),
        )
        return run_mutation(
            profile=profile_key,
            command=command,
            payload=mutation_payload,
            dry_run=False,
            idempotency_key=idempotency_key,
            validation=validation,
            execute=lambda key: client.apply_template(template_id, payload, idempotency_key=key),
        )


def _create_recurrence_mutation(
    *,
    payload: dict[str, Any],
    profile_key: str,
    command: str,
    idempotency_key: str,
    validation: dict[str, Any],
) -> MutationResponse:
    with managed_client(client_factory=build_client) as client:
        _require_capability(
            client,
            feature="recurrence",
            probe_name="probe_recurrence_access",
            error_code="RECURRENCE_CAPABILITY_UNAVAILABLE",
            message="Recurrence mutations are unavailable for this account.",
            fallback_command="webex meeting create",
            fallback_methods=("create_recurrence",),
        )
        return run_mutation(
            profile=profile_key,
            command=command,
            payload=payload,
            dry_run=False,
            idempotency_key=idempotency_key,
            validation=validation,
            execute=lambda key: client.create_recurrence(payload, idempotency_key=key),
        )


def _update_recurrence_mutation(
    *,
    series_id: str,
    payload: dict[str, Any],
    profile_key: str,
    command: str,
    mutation_payload: dict[str, Any],
    idempotency_key: str,
    validation: dict[str, Any],
) -> MutationResponse:
    with managed_client(client_factory=build_client) as client:
        _require_capability(
            client,
            feature="recurrence",
            probe_name="probe_recurrence_access",
            error_code="RECURRENCE_CAPABILITY_UNAVAILABLE",
            message="Recurrence mutations are unavailable for this account.",
            fallback_command="webex meeting create",
            fallback_methods=("update_recurrence",),
        )
        return run_mutation(
            profile=profile_key,
            command=command,
            payload=mutation_payload,
            dry_run=False,
            idempotency_key=idempotency_key,
            validation=validation,
            execute=lambda key: client.update_recurrence(series_id, payload, idempotency_key=key),
        )


@meeting_app.command("list", help="List meetings within a date range or the last N meetings.")
def list_meetings(
    from_value: str | None = typer.Option(None, "--from", help="Start date (YYYY-MM-DD or ISO 8601). Required unless --last is used."),
    to_value: str | None = typer.Option(None, "--to", help="End date (YYYY-MM-DD or ISO 8601). Required unless --last is used."),
    last: int | None = typer.Option(None, "--last", help="Return the N most recent meetings (lookback: 30 days)."),
    tz: str | None = typer.Option(None, "--tz", help="Timezone for interpreting bare dates (e.g. America/New_York)."),
    page_size: int = typer.Option(50, "--page-size", help="Number of results per API page (1-200)."),
    page_token: str | None = typer.Option(None, "--page-token", help="Resume from a page token returned by a previous call."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting list"
    try:
        with profile_scope(None):
            if last is not None and (from_value is not None or to_value is not None):
                raise CliError(
                    DomainCode.VALIDATION_ERROR,
                    "Use either --last or --from/--to, not both.",
                )
            if last is not None:
                if last < 1:
                    raise CliError(
                        DomainCode.VALIDATION_ERROR,
                        "`--last` must be a positive integer.",
                        details={"last": last},
                    )
                now = datetime.now(timezone.utc)
                to_value = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                from_value = (now - timedelta(days=DEFAULT_LAST_LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
            if from_value is None or to_value is None:
                raise CliError(
                    DomainCode.VALIDATION_ERROR,
                    "Provide --from and --to, or use --last N.",
                )
            if page_size < 1 or page_size > 200:
                raise CliError(
                    DomainCode.VALIDATION_ERROR,
                    "`--page-size` must be between 1 and 200.",
                    details={"page_size": page_size},
                )
            from_utc, to_utc = parse_time_range(from_value, to_value, resolve_effective_timezone(tz))
            with managed_client(client_factory=build_client) as client:
                next_page_token: str | None
                if page_token:
                    items, next_page_token = client.list_meetings(
                        from_utc=from_utc,
                        to_utc=to_utc,
                        page_size=page_size,
                        page_token=page_token,
                    )
                    warnings = []
                else:
                    items, warnings = fetch_all_pages(
                        lambda token: client.list_meetings(
                            from_utc=from_utc,
                            to_utc=to_utc,
                            page_size=page_size,
                            page_token=token,
                        ),
                    )
                    next_page_token = None
            normalized = [_normalize_meeting(item) for item in items]
            normalized.sort(key=lambda i: i.get("started_at") or "", reverse=True)
            if last is not None:
                normalized = normalized[:last]
            emit_success(
                command,
                {"items": normalized, "next_page_token": next_page_token},
                as_json=json_output,
                warnings=warnings,
            )
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@meeting_app.command("search", help="Search meetings by text, filters, and sorting.")
def search_meetings(
    query: str = typer.Option(..., "--query", help="Search text."),
    from_value: str | None = typer.Option(None, "--from", help="Start date (YYYY-MM-DD or ISO 8601). Defaults to 30 days ago."),
    to_value: str | None = typer.Option(None, "--to", help="End date (YYYY-MM-DD or ISO 8601). Defaults to now."),
    tz: str | None = typer.Option(None, "--tz", help="Timezone for interpreting bare dates (e.g. America/New_York)."),
    filter_value: str | None = typer.Option(None, "--filter", help="Structured filter expression."),
    sort_value: str | None = typer.Option(None, "--sort", help="Sort fields, e.g. score:desc,started_at:desc."),
    limit: int = typer.Option(DEFAULT_SEARCH_LIMIT, "--limit", help="Maximum number of rows to return."),
    max_pages: int = typer.Option(DEFAULT_SEARCH_MAX_PAGES, "--max-pages", help="Maximum number of upstream pages to fetch."),
    page_token: str | None = typer.Option(None, "--page-token", help="Resume from a page token returned by a previous call."),
    case_sensitive: bool = typer.Option(False, "--case-sensitive", help="Use case-sensitive query and filter evaluation."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting search"
    try:
        with profile_scope(None):
            filter_value = filter_value if isinstance(filter_value, str) else None
            sort_value = sort_value if isinstance(sort_value, str) else None
            page_token = page_token if isinstance(page_token, str) else None
            limit = limit if isinstance(limit, int) and not isinstance(limit, bool) else DEFAULT_SEARCH_LIMIT
            max_pages = max_pages if isinstance(max_pages, int) and not isinstance(max_pages, bool) else DEFAULT_SEARCH_MAX_PAGES
            case_sensitive = case_sensitive if isinstance(case_sensitive, bool) else False
            json_output = json_output if isinstance(json_output, bool) else False
            if not query.strip():
                raise CliError(DomainCode.VALIDATION_ERROR, "`--query` must not be empty.")
            if limit < 1:
                raise CliError(DomainCode.VALIDATION_ERROR, "`--limit` must be a positive integer.", details={"limit": limit})
            sort_field = primary_sort_field(sort_value, default_field="score")
            effective_sort = sort_value if sort_value and sort_value.strip() else "score:desc,started_at:desc"
            from_utc, to_utc = _resolve_search_window(from_value, to_value, tz)
            with managed_client(client_factory=build_client) as client:
                items, next_page_token, warnings = collect_pages(
                    lambda token: client.list_meetings(
                        from_utc=from_utc,
                        to_utc=to_utc,
                        page_size=SEARCH_PAGE_SIZE,
                        page_token=token,
                    ),
                    start_token=page_token,
                    max_pages=max_pages,
                )

            matches: list[dict[str, Any]] = []
            for item in items:
                normalized = _normalize_meeting(item)
                matched, score, snippet = match_query(query, _meeting_search_text(normalized), case_sensitive=case_sensitive)
                if not matched:
                    continue
                normalized["score"] = score
                if not evaluate_filter(filter_value, normalized, MEETING_SEARCH_SCHEMA, case_sensitive=case_sensitive):
                    continue
                normalized["snippet"] = snippet
                matches.append(normalized)

            sorted_matches = sort_items(matches, effective_sort, MEETING_SEARCH_SCHEMA, tie_breaker_field="meeting_id")
            result_items = [
                _meeting_search_result(item, snippet=str(item.get("snippet") or ""), score=int(item.get("score") or 0), sort_field=sort_field)
                for item in sorted_matches[:limit]
            ]
            emit_success(
                command,
                {"items": result_items, "next_page_token": next_page_token},
                as_json=json_output,
                warnings=warnings,
            )
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@meeting_app.command("get", help="Fetch full details for a single meeting.")
def get_meeting(
    meeting_id: str,
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting get"
    try:
        with profile_scope(None):
            meeting_id = validate_id(meeting_id, "meeting_id")
            with managed_client(client_factory=build_client) as client:
                item = client.get_meeting(meeting_id)
            emit_success(command, _normalize_meeting_detail(item), as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@meeting_app.command("join-url", help="Print the join URL for a meeting.")
def join_url(
    meeting_id: str,
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting join-url"
    try:
        with profile_scope(None):
            meeting_id = validate_id(meeting_id, "meeting_id")
            with managed_client(client_factory=build_client) as client:
                item = client.get_meeting_join_url(meeting_id)
            url = item.get("webLink") or item.get("joinWebUrl") or item.get("joinUrl")
            if not url:
                raise CliError(
                    DomainCode.NOT_FOUND,
                    "Join URL not available for meeting.",
                    details={"meeting_id": meeting_id},
                )
            emit_success(command, {"meeting_id": meeting_id, "join_url": url}, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@meeting_app.command("create", help="Create a meeting with dry-run and idempotency support.")
def create_meeting(
    title: str,
    start: str,
    end: str,
    timezone: str | None = typer.Option(None, "--timezone", help="Optional meeting timezone."),
    agenda: str | None = typer.Option(None, "--agenda", help="Optional agenda text."),
    template_id: str | None = typer.Option(None, "--template-id", help="Optional template ID."),
    invitees: str | None = typer.Option(None, "--invitees", help="Comma-separated invitee emails."),
    invitees_file: str | None = typer.Option(None, "--invitees-file", help="Path to invitee file."),
    invitees_file_format: str = typer.Option("lines", "--invitees-file-format", help="Invitee file format: lines or csv."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate locally without performing the mutation."),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="Explicit idempotency key."),
    idempotency_auto: bool = typer.Option(False, "--idempotency-auto", help="Generate an idempotency key automatically."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting create"
    try:
        with profile_scope(None):
            normalized_start, normalized_end = _validate_start_end(start, end)
            normalized_title = _require_non_empty_text(title, "--title")
            parsed_invitees = (
                parse_invitees(invitees=invitees, invitees_file=invitees_file, invitees_file_format=invitees_file_format)
                if invitees or invitees_file
                else []
            )
            profile_key = resolve_profile()
            resolved_idempotency_key = resolve_idempotency_key(idempotency_key, idempotency_auto)
            normalized_template_id = validate_id(template_id, "template_id") if template_id is not None else None
            payload = {
                "title": normalized_title,
                "start": normalized_start,
                "end": normalized_end,
                "timezone": timezone,
                "agenda": agenda,
                "template_id": normalized_template_id,
                "invitees": parsed_invitees,
            }
            validation = {"invitee_count": len(parsed_invitees)}
            response = _execute_mutation(
                profile=profile_key,
                command=command,
                payload=payload,
                dry_run=dry_run,
                idempotency_key=resolved_idempotency_key,
                validation=validation,
                execute=lambda: (
                    run_mutation(
                        profile=profile_key,
                        command=command,
                        payload=payload,
                        dry_run=False,
                        idempotency_key=resolved_idempotency_key,
                        validation=validation,
                        execute=lambda key: _create_meeting_with_client(payload, key),
                    )
                ),
            )
            _emit_mutation(command, response, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@meeting_app.command("update", help="Update meeting fields with idempotency support.")
def update_meeting(
    meeting_id: str,
    title: str | None = typer.Option(None, "--title", help="Updated meeting title."),
    start: str | None = typer.Option(None, "--start", help="Updated start datetime."),
    end: str | None = typer.Option(None, "--end", help="Updated end datetime."),
    agenda: str | None = typer.Option(None, "--agenda", help="Updated agenda text."),
    invitees_add: str | None = typer.Option(None, "--invitees-add", help="Invitees to add."),
    invitees_remove: str | None = typer.Option(None, "--invitees-remove", help="Invitees to remove."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate locally without performing the mutation."),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="Explicit idempotency key."),
    idempotency_auto: bool = typer.Option(False, "--idempotency-auto", help="Generate an idempotency key automatically."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting update"
    try:
        with profile_scope(None):
            meeting_id = validate_id(meeting_id, "meeting_id")
            profile_key = resolve_profile()
            resolved_idempotency_key = resolve_idempotency_key(idempotency_key, idempotency_auto)
            payload: dict[str, Any] = {}
            if title is not None:
                payload["title"] = _require_non_empty_text(title, "--title")
            if start is not None:
                payload["start"] = _parse_host_datetime(start, "start")
            if end is not None:
                payload["end"] = _parse_host_datetime(end, "end")
            if "start" in payload and "end" in payload and payload["start"] >= payload["end"]:
                raise CliError(DomainCode.VALIDATION_ERROR, "`--end` must be later than `--start`.")
            if agenda is not None:
                payload["agenda"] = agenda
            if invitees_add:
                payload["invitees_add"] = parse_invitees(invitees=invitees_add, invitees_file=None, invitees_file_format="lines")
            if invitees_remove:
                payload["invitees_remove"] = parse_invitees(invitees=invitees_remove, invitees_file=None, invitees_file_format="lines")
            if not payload:
                raise CliError(DomainCode.VALIDATION_ERROR, "At least one field must be provided for update.")
            mutation_payload = {"meeting_id": meeting_id, **payload}
            validation = {"field_count": len(payload)}
            response = _execute_mutation(
                profile=profile_key,
                command=command,
                payload=mutation_payload,
                dry_run=dry_run,
                idempotency_key=resolved_idempotency_key,
                validation=validation,
                execute=lambda: (
                    run_mutation(
                        profile=profile_key,
                        command=command,
                        payload=mutation_payload,
                        dry_run=False,
                        idempotency_key=resolved_idempotency_key,
                        validation=validation,
                        execute=lambda key: _update_meeting_with_client(meeting_id, payload, key),
                    )
                ),
            )
            _emit_mutation(command, response, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@meeting_app.command("cancel", help="Cancel a meeting.")
def cancel_meeting(
    meeting_id: str,
    reason: str | None = typer.Option(None, "--reason", help="Optional cancellation reason."),
    notify: bool = typer.Option(True, "--notify/--no-notify", help="Notify invitees of the cancellation."),
    confirm: bool = typer.Option(False, "--confirm", help="Confirm the destructive action."),
    yes: bool = typer.Option(False, "--yes", help="Confirm the destructive action."),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="Explicit idempotency key."),
    idempotency_auto: bool = typer.Option(False, "--idempotency-auto", help="Generate an idempotency key automatically."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting cancel"
    try:
        with profile_scope(None):
            meeting_id = validate_id(meeting_id, "meeting_id")
            _confirm_destructive(command, confirm, yes)
            profile_key = resolve_profile()
            resolved_idempotency_key = resolve_idempotency_key(idempotency_key, idempotency_auto)
            payload = {"meeting_id": meeting_id, "reason": reason, "notify": notify}
            with managed_client(client_factory=build_client) as client:
                response = run_mutation(
                    profile=profile_key,
                    command=command,
                    payload=payload,
                    dry_run=False,
                    idempotency_key=resolved_idempotency_key,
                    validation={},
                    execute=lambda key: client.cancel_meeting(meeting_id, notify=notify, reason=reason, idempotency_key=key),
                )
            _emit_mutation(command, response, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@invitee_app.command("list", help="List meeting invitees.")
def list_invitees(
    meeting_id: str,
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting invitee list"
    try:
        with profile_scope(None):
            meeting_id = validate_id(meeting_id, "meeting_id")
            with managed_client(client_factory=build_client) as client:
                items = client.list_invitees(meeting_id)
            emit_success(command, {"meeting_id": meeting_id, "items": items}, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@invitee_app.command("add", help="Add invitees to a meeting.")
def add_invitees(
    meeting_id: str,
    invitees: str | None = typer.Option(None, "--invitees", help="Comma-separated invitee emails."),
    invitees_file: str | None = typer.Option(None, "--invitees-file", help="Path to invitee file."),
    invitees_file_format: str = typer.Option("lines", "--invitees-file-format", help="Invitee file format: lines or csv."),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="Explicit idempotency key."),
    idempotency_auto: bool = typer.Option(False, "--idempotency-auto", help="Generate an idempotency key automatically."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting invitee add"
    try:
        with profile_scope(None):
            meeting_id = validate_id(meeting_id, "meeting_id")
            parsed_invitees = parse_invitees(
                invitees=invitees,
                invitees_file=invitees_file,
                invitees_file_format=invitees_file_format,
            )
            profile_key = resolve_profile()
            resolved_idempotency_key = resolve_idempotency_key(idempotency_key, idempotency_auto)
            payload = {"meeting_id": meeting_id, "invitees": parsed_invitees}
            with managed_client(client_factory=build_client) as client:
                _require_capability(
                    client,
                    feature="invitees",
                    probe_name="probe_invitees_access",
                    error_code="INVITEE_MUTATION_UNAVAILABLE",
                    message="Invitee mutations are unavailable for this account.",
                    fallback_command="webex meeting update",
                    fallback_methods=("add_invitees",),
                )
                response = run_mutation(
                    profile=profile_key,
                    command=command,
                    payload=payload,
                    dry_run=False,
                    idempotency_key=resolved_idempotency_key,
                    validation={"invitee_count": len(parsed_invitees)},
                    execute=lambda key: client.add_invitees(meeting_id, parsed_invitees, idempotency_key=key),
                )
            _emit_mutation(command, response, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@invitee_app.command("remove", help="Remove invitees from a meeting.")
def remove_invitees(
    meeting_id: str,
    invitees: str | None = typer.Option(None, "--invitees", help="Comma-separated invitee emails."),
    invitees_file: str | None = typer.Option(None, "--invitees-file", help="Path to invitee file."),
    invitees_file_format: str = typer.Option("lines", "--invitees-file-format", help="Invitee file format: lines or csv."),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="Explicit idempotency key."),
    idempotency_auto: bool = typer.Option(False, "--idempotency-auto", help="Generate an idempotency key automatically."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting invitee remove"
    try:
        with profile_scope(None):
            meeting_id = validate_id(meeting_id, "meeting_id")
            parsed_invitees = parse_invitees(
                invitees=invitees,
                invitees_file=invitees_file,
                invitees_file_format=invitees_file_format,
            )
            profile_key = resolve_profile()
            resolved_idempotency_key = resolve_idempotency_key(idempotency_key, idempotency_auto)
            payload = {"meeting_id": meeting_id, "invitees": parsed_invitees}
            with managed_client(client_factory=build_client) as client:
                _require_capability(
                    client,
                    feature="invitees",
                    probe_name="probe_invitees_access",
                    error_code="INVITEE_MUTATION_UNAVAILABLE",
                    message="Invitee mutations are unavailable for this account.",
                    fallback_command="webex meeting update",
                    fallback_methods=("remove_invitees",),
                )
                response = run_mutation(
                    profile=profile_key,
                    command=command,
                    payload=payload,
                    dry_run=False,
                    idempotency_key=resolved_idempotency_key,
                    validation={"invitee_count": len(parsed_invitees)},
                    execute=lambda key: client.remove_invitees(meeting_id, parsed_invitees, idempotency_key=key),
                )
            _emit_mutation(command, response, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@template_app.command("list", help="List available meeting templates.")
def list_templates(
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting template list"
    try:
        with profile_scope(None):
            with managed_client(client_factory=build_client) as client:
                _require_capability(
                    client,
                    feature="templates",
                    probe_name="probe_templates_access",
                    error_code="TEMPLATE_CAPABILITY_UNAVAILABLE",
                    message="Templates are unavailable for this account.",
                    fallback_command="webex meeting create",
                    fallback_methods=("list_meeting_templates",),
                )
                items = client.list_meeting_templates()
            emit_success(command, {"items": items}, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@template_app.command("apply", help="Create a meeting from a template.")
def apply_template(
    template_id: str = typer.Option(..., "--template-id", help="Template ID."),
    start: str = typer.Option(..., "--start", help="Meeting start datetime."),
    end: str = typer.Option(..., "--end", help="Meeting end datetime."),
    invitees: str | None = typer.Option(None, "--invitees", help="Comma-separated invitee emails."),
    invitees_file: str | None = typer.Option(None, "--invitees-file", help="Path to invitee file."),
    invitees_file_format: str = typer.Option("lines", "--invitees-file-format", help="Invitee file format: lines or csv."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate locally without performing the mutation."),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="Explicit idempotency key."),
    idempotency_auto: bool = typer.Option(False, "--idempotency-auto", help="Generate an idempotency key automatically."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting template apply"
    try:
        with profile_scope(None):
            template_id = validate_id(template_id, "template_id")
            normalized_start, normalized_end = _validate_start_end(start, end)
            parsed_invitees = (
                parse_invitees(invitees=invitees, invitees_file=invitees_file, invitees_file_format=invitees_file_format)
                if invitees or invitees_file
                else []
            )
            profile_key = resolve_profile()
            resolved_idempotency_key = resolve_idempotency_key(idempotency_key, idempotency_auto)
            payload = {"start": normalized_start, "end": normalized_end, "invitees": parsed_invitees}
            mutation_payload = {"template_id": template_id, **payload}
            validation = {"invitee_count": len(parsed_invitees)}
            response = _execute_mutation(
                profile=profile_key,
                command=command,
                payload=mutation_payload,
                dry_run=dry_run,
                idempotency_key=resolved_idempotency_key,
                validation=validation,
                execute=lambda: _apply_template_mutation(
                    template_id=template_id,
                    payload=payload,
                    profile_key=profile_key,
                    command=command,
                    mutation_payload=mutation_payload,
                    idempotency_key=resolved_idempotency_key,
                    validation=validation,
                ),
            )
            _emit_mutation(command, response, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@recurrence_app.command("create", help="Create a recurring meeting series.")
def create_recurrence(
    title: str,
    rrule: str,
    start: str,
    duration: int,
    invitees: str | None = typer.Option(None, "--invitees", help="Comma-separated invitee emails."),
    invitees_file: str | None = typer.Option(None, "--invitees-file", help="Path to invitee file."),
    invitees_file_format: str = typer.Option("lines", "--invitees-file-format", help="Invitee file format: lines or csv."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate locally without performing the mutation."),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="Explicit idempotency key."),
    idempotency_auto: bool = typer.Option(False, "--idempotency-auto", help="Generate an idempotency key automatically."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting recurrence create"
    try:
        with profile_scope(None):
            if duration < 1:
                raise CliError(DomainCode.VALIDATION_ERROR, "`--duration` must be a positive integer.", details={"duration": duration})
            normalized_title = _require_non_empty_text(title, "--title")
            normalized_start = _parse_host_datetime(start, "start")
            normalized_rrule = validate_rrule(rrule)
            parsed_invitees = (
                parse_invitees(invitees=invitees, invitees_file=invitees_file, invitees_file_format=invitees_file_format)
                if invitees or invitees_file
                else []
            )
            profile_key = resolve_profile()
            resolved_idempotency_key = resolve_idempotency_key(idempotency_key, idempotency_auto)
            payload = {
                "title": normalized_title,
                "rrule": normalized_rrule,
                "start": normalized_start,
                "duration": duration,
                "invitees": parsed_invitees,
            }
            validation = {"invitee_count": len(parsed_invitees)}
            response = _execute_mutation(
                profile=profile_key,
                command=command,
                payload=payload,
                dry_run=dry_run,
                idempotency_key=resolved_idempotency_key,
                validation=validation,
                execute=lambda: _create_recurrence_mutation(
                    payload=payload,
                    profile_key=profile_key,
                    command=command,
                    idempotency_key=resolved_idempotency_key,
                    validation=validation,
                ),
            )
            _emit_mutation(command, response, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@recurrence_app.command("update", help="Update a recurring meeting series.")
def update_recurrence(
    series_id: str,
    rrule: str | None = typer.Option(None, "--rrule", help="Updated RRULE."),
    from_occurrence: str | None = typer.Option(None, "--from-occurrence", help="Apply changes from this occurrence onward."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate locally without performing the mutation."),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="Explicit idempotency key."),
    idempotency_auto: bool = typer.Option(False, "--idempotency-auto", help="Generate an idempotency key automatically."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting recurrence update"
    try:
        with profile_scope(None):
            series_id = validate_id(series_id, "series_id")
            profile_key = resolve_profile()
            resolved_idempotency_key = resolve_idempotency_key(idempotency_key, idempotency_auto)
            payload: dict[str, Any] = {}
            if rrule is not None:
                payload["rrule"] = validate_rrule(rrule)
            if from_occurrence is not None:
                payload["from_occurrence"] = _parse_host_datetime(from_occurrence, "from_occurrence")
            if not payload:
                raise CliError(DomainCode.VALIDATION_ERROR, "At least one recurrence field must be provided.")
            mutation_payload = {"series_id": series_id, **payload}
            validation = {"field_count": len(payload)}
            response = _execute_mutation(
                profile=profile_key,
                command=command,
                payload=mutation_payload,
                dry_run=dry_run,
                idempotency_key=resolved_idempotency_key,
                validation=validation,
                execute=lambda: _update_recurrence_mutation(
                    series_id=series_id,
                    payload=payload,
                    profile_key=profile_key,
                    command=command,
                    mutation_payload=mutation_payload,
                    idempotency_key=resolved_idempotency_key,
                    validation=validation,
                ),
            )
            _emit_mutation(command, response, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


@recurrence_app.command("cancel", help="Cancel a recurring meeting series.")
def cancel_recurrence(
    series_id: str,
    from_occurrence: str | None = typer.Option(None, "--from-occurrence", help="Cancel from this occurrence onward."),
    confirm: bool = typer.Option(False, "--confirm", help="Confirm the destructive action."),
    yes: bool = typer.Option(False, "--yes", help="Confirm the destructive action."),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="Explicit idempotency key."),
    idempotency_auto: bool = typer.Option(False, "--idempotency-auto", help="Generate an idempotency key automatically."),
    json_output: bool = typer.Option(False, "--json", help="Emit output as a JSON envelope."),
) -> None:
    command = "meeting recurrence cancel"
    try:
        with profile_scope(None):
            series_id = validate_id(series_id, "series_id")
            _confirm_destructive(command, confirm, yes)
            profile_key = resolve_profile()
            resolved_idempotency_key = resolve_idempotency_key(idempotency_key, idempotency_auto)
            normalized_from_occurrence = _parse_host_datetime(from_occurrence, "from_occurrence") if from_occurrence else None
            payload = {"series_id": series_id, "from_occurrence": normalized_from_occurrence}
            with managed_client(client_factory=build_client) as client:
                _require_capability(
                    client,
                    feature="recurrence",
                    probe_name="probe_recurrence_access",
                    error_code="RECURRENCE_CAPABILITY_UNAVAILABLE",
                    message="Recurrence mutations are unavailable for this account.",
                    fallback_command="webex meeting create",
                    fallback_methods=("cancel_recurrence",),
                )
                response = run_mutation(
                    profile=profile_key,
                    command=command,
                    payload=payload,
                    dry_run=False,
                    idempotency_key=resolved_idempotency_key,
                    validation={},
                    execute=lambda key: client.cancel_recurrence(
                        series_id,
                        from_occurrence=normalized_from_occurrence,
                        idempotency_key=key,
                    ),
                )
            _emit_mutation(command, response, as_json=json_output)
    except CliError as exc:
        fail(command, exc, as_json=json_output)
    except Exception as exc:
        handle_unexpected(command, as_json=json_output, exc=exc)


meeting_app.add_typer(invitee_app, name="invitee")
meeting_app.add_typer(template_app, name="template")
meeting_app.add_typer(recurrence_app, name="recurrence")
