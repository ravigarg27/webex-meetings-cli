# webex-meetings-cli

Participant-scoped Webex CLI for meeting discovery, event ingestion, and host workflows.

## Requirements

- Python 3.11+
- A valid Webex access token with participant or host meeting access, depending on the command set you use

## Installation

```bash
pip install .
```

For local development:

```bash
pip install -e .[dev]
```

## Quick Start

Show version:

```bash
webex --version
```

Log in:

```bash
export WEBEX_TOKEN="<token>"
webex auth login
```

OAuth device flow login:

```bash
webex auth login --oauth-device-flow --oauth-client-id "<client_id>"
```

Check identity:

```bash
webex auth whoami --json
```

Search meetings:

```bash
webex meeting search --query "alpha" --from 2026-01-01 --to 2026-01-06 --json
```

Start local event ingress:

```bash
webex event ingress run \
  --public-base-url https://events.example.test \
  --path /webhooks/webex
```

Listen to queued webhook events:

```bash
webex event listen --source webex-webhook --sink jsonl --sink-path ./events.jsonl --json
```

Build the local transcript index:

```bash
WEBEX_SEARCH_LOCAL_INDEX_ENABLED=1 webex transcript index rebuild --from 2026-01-01 --to 2026-01-06 --json
```

Create a host-scoped meeting with dry-run validation:

```bash
webex meeting create "Project Kickoff" 2026-01-10T15:00:00Z 2026-01-10T16:00:00Z \
  --invitees alice@example.test,bob@example.test \
  --dry-run \
  --idempotency-auto \
  --json
```

Use profiles:

```bash
webex profile create work --default-tz America/New_York
webex profile use work
webex --profile work auth whoami --json
```

## Commands

- `webex auth login|logout|whoami`
- `webex profile create|list|show|use|delete`
- `webex meeting list|search|get|join-url|create|update|cancel`
- `webex meeting invitee list|add|remove`
- `webex meeting template list|apply`
- `webex meeting recurrence create|update|cancel`
- `webex event ingress run|status`
- `webex event listen|status|replay`
- `webex event dlq list|purge`
- `webex event checkpoint reset`
- `webex transcript search|segments|speakers|status|get|wait|download|batch`
- `webex transcript index rebuild`
- `webex transcript index key rotate`
- `webex recording list|search|status|download`

Global options:

- `--profile` profile override (`--profile` > `WEBEX_PROFILE` > active profile)
- `--non-interactive` disable prompts and require explicit confirmation flags
- `--request-id` correlation ID for logs and JSON metadata
- `--log-format text|json` structured diagnostic logs

## Output Modes

- Default mode is human-readable output.
- Use `--json` for stable machine-readable envelopes:
  - `ok`, `command`, `data`, `warnings`, `error`, `meta`
  - `meta` includes `request_id`, `timestamp`, `cli_version`, `schema_version`, `duration_ms`, `profile`, `command_mode`
- Current runtime schema version: `1.3`

## Exit Codes

- `0`: success
- `2`: validation, state, or usage error
- `3`: auth required or invalid
- `4`: not found
- `5`: no access, policy restricted, or capability unavailable
- `6`: rate-limited or transient upstream issue
- `7`: artifact not ready or wait timeout
- `8`: overwrite or mutation conflict
- `10`: internal error

## Security Notes

- Prefer `WEBEX_TOKEN` or `--token-stdin`; `--token` is blocked by default.
- Fallback credential storage is used only if keyring is unavailable.
- Default fallback policy is `ci_strict`: CI and non-interactive sessions must use keyring unless `WEBEX_CREDENTIAL_FALLBACK_POLICY=allow_file_fallback`.
- Recording download URLs are validated and local/private hosts are blocked.
- Local transcript index encryption uses secure keyring storage when available. Fallback key storage requires explicit `WEBEX_SEARCH_LOCAL_INDEX_ALLOW_PLAINTEXT=1`.
- Optional checksum verification:
  - `webex recording download ... --verify-checksum`
  - `webex transcript download ... --verify-checksum`

## Phase 2X Notes

- Transcript search falls back to the local encrypted index when upstream transcript search capability is unavailable and the index has been built.
- Event ingress auto-registration reconciles profile-scoped webhook subscriptions for `meetings`, `recordings`, and `meetingTranscripts`.
- Destructive host and event commands require `--confirm` or `--yes` when `--non-interactive` is set.

## Live E2E

Live smoke tests are opt-in:

```bash
WEBEX_E2E_LIVE=1 WEBEX_TEST_TOKEN="<token>" pytest -q tests/e2e/test_cli_smoke.py::test_cli_smoke_live_mode
```

Optional date controls:

- `WEBEX_TEST_FROM` / `WEBEX_TEST_TO`
- `WEBEX_TEST_LAST_DAYS`

## Development

Run all tests:

```bash
pytest -q
```
