# Webex Meetings CLI Phase 1 Implementation Spec

Date: 2026-03-02  
Status: Ready for implementation (contracts tightened)  
Owner: Engineering  
Depends on: `docs/2026-03-02-webex-meetings-cli-phase1.md`

## 1. Purpose

This document converts the Phase 1 plan into implementation-level contracts.

Goals:

1. Remove ambiguous behavior.
2. Define stable interfaces for CLI, JSON output, exit codes, and filesystem behavior.
3. Provide a command-by-command implementation checklist and test matrix.

Non-goals:

1. Rewriting product scope.
2. Adding Phase 2+ features.

## 2. Implementation Constraints

1. Python: 3.11+.
2. CLI framework: Typer.
3. HTTP client: `httpx` with shared client lifecycle.
4. Platform support for Phase 1: Windows + macOS + Linux.
5. Phase 1 persona: single user, single active profile.

## 3. Core Architecture

Package layout:

1. `webex_cli/commands/`
2. `webex_cli/client/`
3. `webex_cli/models/`
4. `webex_cli/output/`
5. `webex_cli/errors/`
6. `webex_cli/config/`
7. `webex_cli/fs/`

Required internal interfaces:

1. `WebexApiClient`: typed methods for auth/meetings/transcripts/recordings.
2. `CredentialStore`: get/set/clear credentials and profile metadata.
3. `JsonRenderer`: emits canonical JSON envelope.
4. `TableRenderer`: human-readable output for non-JSON mode.
5. `ExitCodeMapper`: maps domain errors to deterministic exit codes.
6. `DownloadManager`: atomic file write, overwrite policy, checksum/size validation hooks.

## 4. Identity and Resource Model

### 4.1 IDs accepted by CLI

Phase 1 CLI accepts an argument named `<meetingId>`, but implementation must support:

1. Meeting ID.
2. Meeting UUID.
3. Occurrence identifier if required by upstream APIs.

Normalization contract:

1. `IdResolver` resolves the input to canonical identifiers required by downstream calls.
2. If identifier format is syntactically invalid, return `VALIDATION_ERROR` (`exit 2`).
3. If syntactically valid but not found upstream, return `NOT_FOUND` (`exit 4`) with details indicating which identifier failed.

### 4.2 Participant scope

1. `--participant` in Phase 1 accepts only `me`.
2. Any other value is a validation error (`exit 2`).
3. Scope filter is applied server-side when possible; otherwise client-side with explicit warning in `warnings`.

## 5. Auth Contract

### 5.1 Commands

1. `webex auth login --token <token>`
2. `webex auth logout`
3. `webex auth whoami [--json]`

### 5.2 Behavior

1. `login`:
   - `--token` is required in Phase 1.
   - Missing token is a validation error (`exit 2`).
   - Validates token by calling identity endpoint before storing.
2. `logout`:
   - Deletes local credential material.
   - Returns success even if already logged out (idempotent).
3. `whoami`:
   - Requires credential.
   - Validates token with upstream call.
   - Emits user/org/site metadata and token state.

### 5.3 Credential storage

1. Prefer OS keychain backend.
2. Fallback file store only when keychain unavailable.
3. File fallback path:
   - Windows: `%APPDATA%/webex-cli/credentials.json`
   - macOS/Linux: `${XDG_CONFIG_HOME:-~/.config}/webex-cli/credentials.json`
4. File fallback permissions must be user-only.
5. Never print or log token.

### 5.4 Phase 1 auth mode and permissions

1. Phase 1 auth mode is token-only (`--token`).
2. OAuth device flow is explicitly deferred to Phase 1.1.
3. Token validation during `login` is capability-based:
   - validate identity retrieval via `GET /v1/people/me` expecting HTTP 200
   - validate participant meetings access via `GET /v1/meetings` on a narrow date range expecting HTTP 200
4. Minimum required token capabilities for Phase 1:
   - read own user profile
   - read meetings as participant
   - recording/transcript capabilities are validated lazily at command runtime
5. If token lacks capability, return `AUTH_INVALID` (`exit 3`) with actionable detail.
6. Capability probe error mapping:
   - HTTP 401/403 => `AUTH_INVALID` (`exit 3`)
   - HTTP 429/5xx => `RATE_LIMITED` or `UPSTREAM_UNAVAILABLE` (`exit 6`)
   - network timeout/connection errors => `UPSTREAM_UNAVAILABLE` (`exit 6`)

## 6. Date/Time Contract

1. `--from` is inclusive.
2. `--to` is exclusive.
3. Input accepts:
   - Full ISO8601 timestamp with timezone.
   - Date-only (`YYYY-MM-DD`) interpreted at `00:00:00` in effective timezone.
4. Effective timezone:
   - command `--tz` if present
   - else profile default timezone
   - else local system timezone
5. If `from >= to`, validation error (`exit 2`).
6. All JSON timestamps are emitted as RFC3339 UTC.

## 7. Output Contract

### 7.1 Canonical JSON envelope (all commands with `--json`)

```json
{
  "ok": true,
  "command": "transcript status",
  "data": {},
  "warnings": [],
  "error": null,
  "meta": {
    "request_id": "optional-correlation-id",
    "timestamp": "2026-03-02T00:00:00Z",
    "cli_version": "1.0.0",
    "schema_version": "1.0"
  }
}
```

Failure envelope:

```json
{
  "ok": false,
  "command": "transcript download",
  "data": null,
  "warnings": [],
  "error": {
    "code": "NO_ACCESS",
    "message": "Transcript exists but caller has no access",
    "retryable": false,
    "details": {}
  },
  "meta": {
    "request_id": "optional-correlation-id",
    "timestamp": "2026-03-02T00:00:00Z",
    "cli_version": "1.0.0",
    "schema_version": "1.0"
  }
}
```

### 7.2 Format interaction rules

1. `--json` controls envelope mode.
2. Domain format flags (`--format txt|vtt|json|text`) control payload representation inside `data`.
3. `--json` + `--format json` is valid and means structured payload nested under `data`.

### 7.3 Human-readable mode

1. Human mode is stable for users but not machine contract.
2. Errors in human mode still include actionable reason and remediation hint.

## 8. Transcript Status Canonical Mapping

Canonical values:

1. `not_recorded`
2. `processing`
3. `ready`
4. `failed`
5. `no_access`
6. `not_found`
7. `transcript_disabled`

Mapping policy:

1. Upstream status values are mapped in a single `TranscriptStatusMapper`.
2. Unknown upstream status maps to `failed` with warning `UNMAPPED_TRANSCRIPT_STATUS`.

## 8.1 Recording Status Canonical Mapping

Canonical values:

1. `not_recorded`
2. `processing`
3. `ready`
4. `failed`
5. `no_access`
6. `not_found`
7. `recording_disabled`

Mapping policy:

1. Upstream status values are mapped in a single `RecordingStatusMapper`.
2. Unknown upstream status maps to `failed` with warning `UNMAPPED_RECORDING_STATUS`.

## 8.2 Wait Behavior by Transcript Status

`transcript wait` handling:

1. `processing`: continue polling.
2. `ready`: stop, return success (`exit 0`).
3. `failed`: stop, return internal failure (`exit 10`).
4. `no_access`: stop, return forbidden (`exit 5`).
5. `not_found`: stop, return not found (`exit 4`).
6. `transcript_disabled`: stop, return forbidden/policy (`exit 5`).
7. `not_recorded`: stop, return not found/artifact missing (`exit 4`).

## 9. Exit Code Matrix

Global codes:

1. `0` success
2. `2` invalid usage/validation
3. `3` auth required/auth failed
4. `4` not found
5. `5` forbidden/no access
6. `6` rate-limited/transient upstream/network
7. `7` artifact not ready or timeout waiting
8. `8` conflict/overwrite prevented
9. `10` internal/unexpected

Command-level rules:

1. `transcript wait` timeout => `7`.
2. `transcript status processing` in normal status command => `0` (status is data, not command failure).
3. `download` with existing file and no `--overwrite` => `8`.
4. `batch`:
   - Continue mode: non-zero only for command-level failures.
   - Fail-fast mode (`--fail-fast` in implementation): exits first failing item code.
5. `transcript wait` status mapping is defined in Section 8.2 and is normative.

## 10. Retry, Timeout, and Rate Limits

1. Retryable categories:
   - HTTP 429
   - HTTP 5xx
   - network timeout/connection reset
2. Default retry policy:
   - attempts: 5
   - base delay: 0.5s
   - exponential factor: 2
   - full jitter: enabled
   - max delay: 8s
3. Respect explicit server retry headers when present.
4. Non-retryable 4xx fail immediately.
5. Default request timeout: 30s; download timeout: 300s.

## 11. Filesystem and Download Contract

1. Parent directories auto-created for download commands.
2. Atomic write:
   - write to temp file in same directory
   - rename to target only on success
3. Partial failures:
   - temp file removed on failure unless `--keep-partial` (not in Phase 1 CLI surface; internal false).
4. Overwrite behavior:
   - default no overwrite
   - `--overwrite` required to replace existing file
5. Filename strategy for batch:
   - `<meeting_id>_<start_utc_compact>_<artifact_id>.<format>`
   - sanitize invalid filesystem characters
   - if `artifact_id` unavailable, use deterministic hash suffix:
     - algorithm: SHA-256
     - canonical input: `<meeting_id>|<start_time_utc_rfc3339>|<download_url_or_empty>`
     - suffix: first 12 lowercase hex characters
6. Collision strategy in batch:
   - if exists and no overwrite => item status `skipped`
   - if overwrite => replace atomically

## 12. Command-by-Command Specs

### 12.1 `meeting list`

Signature:

1. `webex meeting list --from <ISO8601> --to <ISO8601> [--participant me] [--tz <IANA_TZ>] [--page-size <n>] [--page-token <token>] [--json]`

Inputs:

1. `--from`, `--to` required
2. `--tz` optional (applies to input parsing and display)
3. `--participant` optional (`me` only)
4. `--page-size` optional default 50 max 200
5. `--page-token` optional

Outputs:

1. Meeting summaries sorted by start time descending.
2. Auto-fetch-all behavior (default):
   - command follows pagination until no `next_page_token`
   - `next_page_token` in final JSON response is always `null`
3. If `--page-token` is provided, traversal starts from that token and still auto-fetches remaining pages.
4. Safety guard: hard cap `max_items=10000`; exceeding cap returns `UPSTREAM_UNAVAILABLE` (`exit 6`) with warning `MAX_ITEMS_GUARD_HIT`.

### 12.2 `meeting get`

Signature:

1. `webex meeting get <meetingId> [--json]`

1. Resolve meeting identifiers.
2. Return details plus artifact hints:
   - transcript availability hint
   - recording availability hint

### 12.3 `meeting join-url`

Signature:

1. `webex meeting join-url <meetingId> [--json]`

1. Return canonical join URL for resolved meeting.
2. `not found` => `exit 4`.

### 12.4 `transcript status`

Signature:

1. `webex transcript status <meetingId> [--json]`

1. Returns canonical transcript status.
2. Includes source metadata (e.g., updated_at, reason when failed).

### 12.5 `transcript get`

Signature:

1. `webex transcript get <meetingId> [--format text|json] [--json]`

1. Fetch transcript payload but do not write file.
2. `--format`:
   - `text` plain text
   - `json` structured transcript object

### 12.6 `transcript wait`

Signature:

1. `webex transcript wait <meetingId> [--timeout <sec>] [--interval <sec>] [--json]`

1. Poll interval default 10s.
2. Timeout default 600s.
3. Stop conditions are fully defined in Section 8.2.
4. Timeout without terminal status => `exit 7`.

### 12.7 `transcript download`

Signature:

1. `webex transcript download <meetingId> --format txt|vtt|json --out <path> [--overwrite] [--json]`

1. Requires `--out` and `--format`.
2. Writes atomically.
3. Returns output path in JSON `data`.

### 12.8 `transcript batch`

Signature:

1. `webex transcript batch --from <ISO8601> --to <ISO8601> --download-dir <dir> [--tz <IANA_TZ>] [--format txt|vtt|json] [--continue-on-error] [--fail-fast] [--json]`

Inputs:

1. `--from`, `--to`, `--download-dir` required
2. `--tz` optional
3. `--format` default `txt`
4. Mode flags:
   - default mode is continue-on-error
   - `--continue-on-error` explicit continue mode
   - `--fail-fast` explicit stop-on-first-failure mode
   - `--continue-on-error` and `--fail-fast` together => validation error (`exit 2`)

Output `results[]` item schema:

1. `meeting_id`
2. `status`: `success|skipped|failed`
3. `output_path` nullable
4. `error_code` nullable
5. `error_message` nullable

### 12.9 `recording list`

Signature:

1. `webex recording list --from <ISO8601> --to <ISO8601> [--participant me] [--tz <IANA_TZ>] [--page-size <n>] [--page-token <token>] [--json]`

1. Same date semantics as `meeting list`.
2. Supports pagination:
   - `--page-size` optional default 50 max 200
   - `--page-token` optional
   - auto-fetch-all enabled by default, same rules as Section 12.1
3. Includes recording metadata:
   - `recording_id`
   - `meeting_id`
   - `occurrence_id` nullable
   - `started_at`
   - `duration_seconds` nullable
   - `size_bytes` nullable
   - `downloadable` boolean

### 12.10 `recording status`

1. Signature: `webex recording status <meetingId> [--recording-id <recordingId>] [--json]`.
2. Returns `not_recorded|processing|ready|failed|no_access|not_found|recording_disabled`.
3. Resolution rules:
   - if `--recording-id` provided, status is for that recording only
   - if omitted and exactly one recording matches meeting => use it
   - if omitted and multiple recordings match => `AMBIGUOUS_RECORDING` (`exit 2`)

### 12.11 `recording download`

1. Signature: `webex recording download <meetingId> --out <path> [--recording-id <recordingId>] [--quality <best|high|medium>] [--overwrite] [--json]`.
2. Requires `--out`.
3. `--quality` default `best`, fallback behavior documented in output warning if exact quality unavailable.
4. Recording resolution follows Section 12.10 rules.

### 12.12 Upstream endpoint authority and precedence

Phase 1 authoritative endpoint families (via `WebexApiClient`) are:

1. Identity and token validation:
   - primary: `/v1/people/me`
2. Participant-scoped meeting discovery:
   - primary: `/v1/meetings` with date-range filters and participant scope
3. Recording discovery and download metadata:
   - primary: `/v1/recordings`
4. Transcript discovery/status/content:
   - primary: `/v1/meetingTranscripts`

Precedence and fallback rules:

1. `meeting list/get` uses meetings endpoint as source of truth.
2. `recording list/status` uses recordings endpoint as source of truth.
3. `transcript status/get` uses transcripts endpoint as source of truth.
4. If transcript endpoint is unavailable for tenant policy/product reasons, map to `transcript_disabled` instead of generic failure.
5. If recording endpoint is unavailable for tenant policy/product reasons, map to `recording_disabled` instead of generic failure.
6. Endpoint availability detection:
   - 403 with normalized upstream error code in `{"FEATURE_DISABLED","ORG_POLICY_RESTRICTED"}` => disabled status mapping
   - 404 => `NOT_FOUND` (never interpreted as disabled)
   - other 4xx => mapped by normal error taxonomy
   - 429/5xx/network => transient (`exit 6`)

### 12.13 API Base URL Contract

1. "API endpoint" here means the API base URL host used for all resource paths.
2. Default base URL: `https://webexapis.com`.
3. All endpoint paths are resolved as `<base_url>/v1/...`.
4. Base URL override precedence:
   - env var `WEBEX_API_BASE_URL`
   - config file key `api_base_url`
   - default `https://webexapis.com`
5. Overrides must use `https` scheme; otherwise validation error (`exit 2`).
6. The resolved base URL is echoed in debug logs only, never with auth tokens.

### 12.14 Per-command JSON `data` minimum schemas

1. `auth whoami`:
   - `user_id` string
   - `display_name` string
   - `primary_email` string
   - `org_id` string|null
   - `site_url` string|null
   - `token_state` enum(`valid`,`invalid`,`expired`)
2. `meeting list`:
   - `items` array
   - `next_page_token` string|null
3. `meeting get`:
   - `meeting_id` string
   - `join_url` string|null
   - `transcript_hint` string
   - `recording_hint` string
4. `transcript status`:
   - `meeting_id` string
   - `status` enum from Section 8
   - `updated_at` string|null
   - `reason` string|null
5. `transcript get`:
   - `meeting_id` string
   - `format` enum(`text`,`json`)
   - `content` string|object
6. `transcript download`:
   - `meeting_id` string
   - `format` enum(`txt`,`vtt`,`json`)
   - `output_path` string
7. `transcript batch`:
   - `total_meetings` number
   - `success` number
   - `skipped` number
   - `failed` number
   - `results` array
8. `recording list`:
   - `items` array
   - `next_page_token` string|null
9. `recording status`:
   - `meeting_id` string
   - `recording_id` string|null
   - `status` enum from Section 8.1
10. `recording download`:
   - `meeting_id` string
   - `recording_id` string
   - `quality` string
   - `output_path` string

Array item schemas:

1. `meeting list.items[]`:
   - `meeting_id` string
   - `meeting_uuid` string|null
   - `title` string
   - `started_at` string (RFC3339 UTC)
   - `ended_at` string|null (RFC3339 UTC)
   - `host_email` string|null
2. `recording list.items[]`:
   - `recording_id` string
   - `meeting_id` string
   - `occurrence_id` string|null
   - `started_at` string (RFC3339 UTC)
   - `duration_seconds` number|null
   - `size_bytes` number|null
   - `downloadable` boolean
3. `transcript batch.results[]`:
   - `meeting_id` string
   - `status` enum(`success`,`skipped`,`failed`)
   - `output_path` string|null
   - `error_code` string|null
   - `error_message` string|null

## 13. Error Taxonomy (Domain Codes)

Required domain codes:

1. `VALIDATION_ERROR`
2. `AUTH_REQUIRED`
3. `AUTH_INVALID`
4. `NOT_FOUND`
5. `NO_ACCESS`
6. `RATE_LIMITED`
7. `UPSTREAM_UNAVAILABLE`
8. `ARTIFACT_NOT_READY`
9. `OVERWRITE_CONFLICT`
10. `DOWNLOAD_FAILED`
11. `AMBIGUOUS_RECORDING`
12. `TRANSCRIPT_DISABLED`
13. `RECORDING_DISABLED`
14. `INTERNAL_ERROR`

Each domain code maps to:

1. exit code
2. retryability
3. default user message template

### 13.1 Domain Code Mapping Table (Authoritative)

1. `VALIDATION_ERROR` -> exit `2`, retryable `false`
2. `AUTH_REQUIRED` -> exit `3`, retryable `false`
3. `AUTH_INVALID` -> exit `3`, retryable `false`
4. `NOT_FOUND` -> exit `4`, retryable `false`
5. `NO_ACCESS` -> exit `5`, retryable `false`
6. `RATE_LIMITED` -> exit `6`, retryable `true`
7. `UPSTREAM_UNAVAILABLE` -> exit `6`, retryable `true`
8. `ARTIFACT_NOT_READY` -> exit `7`, retryable `true`
9. `OVERWRITE_CONFLICT` -> exit `8`, retryable `false`
10. `DOWNLOAD_FAILED` -> exit `10`, retryable `false`
11. `AMBIGUOUS_RECORDING` -> exit `2`, retryable `false`
12. `TRANSCRIPT_DISABLED` -> exit `5`, retryable `false`
13. `RECORDING_DISABLED` -> exit `5`, retryable `false`
14. `INTERNAL_ERROR` -> exit `10`, retryable `false`

## 14. Test Specification

### 14.1 Unit

1. Argument validation for all commands.
2. Date parsing and timezone conversion.
3. Exit code mapping table completeness.
4. Transcript status mapping from upstream values.
5. JSON envelope shape snapshot tests.
6. Filename sanitizer behavior.

### 14.2 Integration (mocked API)

1. Auth login success/failure.
2. Token invalidation mid-run.
3. Auto-fetch-all pagination:
   - starts at first page and traverses to completion
   - starts from provided `page_token` and traverses to completion
4. Transcript wait lifecycle (`processing -> ready` and timeout path).
5. Recording permission denial.
6. Retry on `429` with retry headers.
7. Retry exhaustion on `5xx`.
8. `transcript wait` terminal mappings for `not_recorded|not_found|no_access|transcript_disabled`.
9. recording ambiguity flow without `--recording-id`.

### 14.3 E2E smoke

1. `auth login/whoami/logout`
2. `meeting list/get/join-url`
3. `transcript status/get/download/wait`
4. `transcript batch` in continue and fail-fast modes
5. `recording list/status/download`

E2E prerequisites:

1. Env var `WEBEX_TEST_TOKEN` must be present for live e2e.
2. Env var `WEBEX_TEST_FROM` and `WEBEX_TEST_TO` for deterministic date range.
3. If env vars absent, e2e suite runs in mocked mode only and does not fail CI.
4. Live e2e must be opt-in via `WEBEX_E2E_LIVE=1`.

### 14.4 Filesystem tests

1. Atomic rename success.
2. Temp cleanup on failure.
3. Overwrite conflict behavior.
4. Cross-platform path handling.

## 15. Milestone Breakdown (Execution Ready)

1. `M1`: Scaffold, config + credential store, base error model, JSON envelope.
2. `M1.1`: Exit code map + common validation/date parsing.
3. `M2`: Meeting commands + pagination contract.
4. `M3`: Transcript status/get/wait + status mapper.
5. `M4`: Transcript download + batch + file collision policies.
6. `M5`: Recording commands + quality fallback behavior.
7. `M6`: Reliability hardening + CI matrix + release packaging.

Definition of implementation-ready completion for each milestone:

1. Code merged.
2. Unit + integration tests passing.
3. Command docs and JSON examples updated.

## 16. Resolved Decisions (2026-03-02)

1. Auth mode for Phase 1: token-only with `--token`; OAuth device flow deferred to Phase 1.1.
2. Authoritative endpoint families:
   - identity: `/v1/people/me`
   - meetings: `/v1/meetings`
   - recordings: `/v1/recordings`
   - transcripts: `/v1/meetingTranscripts`
3. `whoami` minimum metadata contract:
   - `user_id`
   - `display_name`
   - primary email
   - `org_id` (nullable if unavailable)
   - `site_url` (nullable if unavailable)
   - token state (`valid`, `invalid`, `expired`)
4. Recording statuses use a separate canonical enum (`recording_disabled` instead of `transcript_disabled`), while retaining shared lifecycle semantics (`processing`, `ready`, `failed`, etc).
5. `auth login` requires `--token` in Phase 1; interactive token acquisition is out of scope.
6. `recording status` and `recording download` support optional `--recording-id` for disambiguation; ambiguous matches error with `AMBIGUOUS_RECORDING`.
7. `AMBIGUOUS_RECORDING` maps to exit code `2`.
8. Listing commands (`meeting list`, `recording list`) use auto-fetch-all pagination by default.
9. API base URL defaults to `https://webexapis.com` with override via `WEBEX_API_BASE_URL` or config `api_base_url`.

This spec is executable now.
