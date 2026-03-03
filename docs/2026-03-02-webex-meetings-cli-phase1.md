# Webex Meetings CLI Phase 1 Plan

Date: 2026-03-02
Status: Proposed
Owner: Agent-assisted planning
Scope: Phase 1 CLI for participant-scoped meeting, transcript, and recording retrieval

Implementation note: This is the product-scope plan. Engineering contracts and authoritative command behavior are defined in `docs/2026-03-02-webex-meetings-cli-phase1-implementation-spec.md`.

## 1. Goal

Build a production-ready `webex` CLI that allows an authenticated user to:

1. List meetings where they participated.
2. Check transcript and recording availability.
3. Retrieve and download transcripts.
4. Download recordings.
5. Run the same workflows in interactive and automation-safe modes.

Primary persona: individual user pulling their own meeting artifacts.

## 2. Scope Decisions

### In Phase 1

1. Authentication basics (`login`, `logout`, `whoami`).
2. Meeting discovery for meetings where the user is a participant (`--participant me` default).
3. Transcript lifecycle commands: status, get, wait, download, batch.
4. Recording commands: list/status and download.
5. Global machine-friendly output (`--json`) and deterministic exit codes.
6. Batch behavior default: `continue-on-error`.

### Deferred to Phase 2

1. Meeting search by free text.
2. Transcript full-text search.
3. Speaker-segment helpers.
4. Multi-profile switching UX.
5. Webhook/event listener commands.
6. Host workflows: create/update/cancel, invitees, recurring/templates.

## 3. Command Surface (Phase 1)

Base command: `webex`

## 3.1 Auth

1. `webex auth login [--token <token>] [--non-interactive]`
2. `webex auth logout`
3. `webex auth whoami [--json]`

Behavior:

1. `login` stores credentials for the active local profile.
2. `whoami` validates token/session and prints identity + org/site metadata.
3. `logout` clears local credentials and returns success if local clear completes.

## 3.2 Meetings

1. `webex meeting list --from <ISO8601> --to <ISO8601> [--participant me] [--page-size <n>] [--page-token <token>] [--json]`
2. `webex meeting get <meetingId> [--json]`
3. `webex meeting join-url <meetingId> [--json]`

Behavior:

1. `--participant` defaults to `me` for this phase.
2. `meeting get` returns meeting details and artifact hints (recording/transcript states if available).

## 3.3 Transcripts

1. `webex transcript status <meetingId> [--json]`
2. `webex transcript get <meetingId> [--format text|json] [--json]`
3. `webex transcript wait <meetingId> [--timeout <sec>] [--interval <sec>] [--json]`
4. `webex transcript download <meetingId> --format txt|vtt|json --out <path> [--overwrite] [--json]`
5. `webex transcript batch --from <ISO8601> --to <ISO8601> --download-dir <dir> [--format txt|vtt|json] [--continue-on-error] [--json]`

Behavior:

1. `wait` polls until transcript is `ready`, `failed`, or timeout.
2. `batch` default is continue-on-error; report aggregate summary.
3. `download` creates parent directories when needed.

## 3.4 Recordings

1. `webex recording list --from <ISO8601> --to <ISO8601> [--participant me] [--json]`
2. `webex recording status <meetingId> [--json]`
3. `webex recording download <meetingId> --out <path> [--quality <best|high|medium>] [--overwrite] [--json]`

Behavior:

1. Recording commands support participant-scoped retrieval where API permissions allow.
2. `recording download` emits explicit permission and policy errors.

## 4. Output Contract

## 4.1 Global JSON Envelope

All `--json` responses should follow:

```json
{
  "ok": true,
  "command": "transcript status",
  "data": {},
  "warnings": [],
  "meta": {
    "request_id": "optional-correlation-id",
    "timestamp": "2026-03-02T00:00:00Z"
  }
}
```

Failure shape:

```json
{
  "ok": false,
  "command": "transcript download",
  "error": {
    "code": "NO_ACCESS",
    "message": "Transcript exists but caller has no access",
    "retryable": false,
    "details": {}
  }
}
```

## 4.2 Transcript Status Values

Canonical status values:

1. `not_recorded`
2. `processing`
3. `ready`
4. `failed`
5. `no_access`
6. `not_found`
7. `transcript_disabled`

## 4.3 Batch Summary Shape

```json
{
  "ok": true,
  "data": {
    "total_meetings": 42,
    "success": 30,
    "skipped": 8,
    "failed": 4,
    "results": [
      {
        "meeting_id": "abc",
        "status": "success",
        "output_path": "C:/tmp/abc.txt"
      }
    ]
  }
}
```

## 5. Exit Codes

1. `0` success
2. `2` invalid CLI usage or validation error
3. `3` auth required or auth failed
4. `4` not found
5. `5` no access/forbidden
6. `6` rate limited or transient upstream error
7. `7` artifact not ready (`processing`)
8. `8` conflict/overwrite prevented
9. `10` unexpected internal error

Notes:

1. `transcript wait` timeout exits with `7`.
2. `batch` exits non-zero only when command-level failure occurs (not per-item failures in continue mode).

## 6. Non-Functional Requirements

1. Retry with exponential backoff + jitter for 429/5xx and network timeouts.
2. Respect API rate-limit headers when present.
3. Timezone-safe parsing and display (default local, optional `--tz`).
4. Redact sensitive tokens from logs and error output.
5. Support non-interactive CI usage with no prompts when `--non-interactive` is set.

## 7. Technical Architecture (Lean)

1. Language: Python 3.11+.
2. CLI framework: Typer.
3. HTTP: `httpx` with shared client, retries, timeout policy.
4. Config: local file in user config dir (profile, token metadata, defaults).
5. Modules:
   - `webex_cli/commands/` (auth, meeting, transcript, recording)
   - `webex_cli/client/` (API adapter)
   - `webex_cli/models/` (typed payload models)
   - `webex_cli/output/` (table/json renderers)
   - `webex_cli/errors/` (error mapping to exit codes)

## 8. Implementation Milestones

1. `M1`: Project scaffold, auth commands, global JSON envelope, exit-code plumbing.
2. `M2`: Meeting list/get/join-url with participant default.
3. `M3`: Transcript status/get/download/wait.
4. `M4`: Transcript batch with continue-on-error summary.
5. `M5`: Recording list/status/download.
6. `M6`: Hardening pass (retry, error taxonomy, docs, smoke tests).

## 9. Test Plan

1. Unit tests:
   - command arg parsing and validation
   - API error-to-exit-code mapping
   - output envelope and schema contracts
2. Integration tests (mocked API):
   - transcript lifecycle `processing -> ready`
   - batch continue-on-error summary correctness
   - recording download permission failures
3. CLI e2e smoke:
   - auth login/whoami
   - meeting list in date range
   - transcript get/download
   - recording download

## 10. Definition of Done (Phase 1)

1. User can fetch and download accessible transcripts for meetings they participated in for a date range.
2. User can download accessible recordings for meetings they participated in.
3. All Phase 1 commands support `--json`.
4. Exit codes are stable and documented.
5. CI test suite covers core happy path and key failure modes.
