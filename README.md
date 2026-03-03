# webex-meetings-cli

Participant-scoped Webex CLI for meeting discovery and artifact workflows (transcripts, recordings).

## Requirements

- Python 3.11+
- A valid Webex access token with participant meeting access

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

Log in (recommended: environment variable):

```bash
export WEBEX_TOKEN="<token>"
webex auth login
```

Alternative login methods:

```bash
echo "<token>" | webex auth login --token-stdin
```

Legacy insecure token-arg mode (explicit opt-in):

```bash
WEBEX_ALLOW_INSECURE_TOKEN_ARG=1 webex auth login --token "<token>"
```

Check identity:

```bash
webex auth whoami --json
```

List meetings:

```bash
webex meeting list --from 2026-01-01 --to 2026-01-06 --json
```

Download a transcript:

```bash
webex transcript download <meeting_id> --format txt --out ./transcript.txt
```

Download a recording:

```bash
webex recording download <meeting_id> --out ./recording.mp4
```

## Commands

- `webex auth login|logout|whoami`
- `webex meeting list|get|join-url`
- `webex transcript status|get|wait|download|batch`
- `webex recording list|status|download`

## Output Modes

- Default mode is human-readable output.
- Use `--json` for stable machine-readable envelopes:
  - `ok`, `command`, `data`, `warnings`, `error`, `meta`

## Exit Codes

- `0`: success
- `2`: validation or usage error
- `3`: auth required/invalid
- `4`: not found
- `5`: no access / policy restricted
- `6`: rate-limited or transient upstream issue
- `7`: artifact not ready / wait timeout
- `8`: overwrite conflict
- `10`: internal error

## Security Notes

- Prefer `WEBEX_TOKEN` or `--token-stdin`; `--token` is blocked by default.
- Fallback credential storage is used only if keyring is unavailable.
- Recording download URLs are validated and local/private hosts are blocked.

## Live E2E

Live smoke tests are opt-in:

```bash
WEBEX_E2E_LIVE=1 WEBEX_TEST_TOKEN="<token>" pytest -q tests/e2e/test_cli_smoke.py::test_cli_smoke_live_mode
```

Optional date controls:

- `WEBEX_TEST_FROM` / `WEBEX_TEST_TO` (explicit window)
- or `WEBEX_TEST_LAST_DAYS` (default: `5`)

## Development

Run all tests:

```bash
pytest -q
```
