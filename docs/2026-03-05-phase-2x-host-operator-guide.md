# Phase 2X Host Operator Guide

## Safety model

Host mutations are guarded by three controls:

1. `--dry-run` validates locally without sending the mutation
2. `--idempotency-key` or `--idempotency-auto` guards retries
3. destructive commands require `--confirm` or `--yes` in non-interactive mode

## Create and update

Create:

```bash
webex meeting create "Project Kickoff" 2026-01-10T15:00:00Z 2026-01-10T16:00:00Z \
  --invitees alice@example.test,bob@example.test \
  --idempotency-auto \
  --json
```

Dry-run:

```bash
webex meeting create "Project Kickoff" 2026-01-10T15:00:00Z 2026-01-10T16:00:00Z \
  --dry-run \
  --idempotency-auto \
  --json
```

Update:

```bash
webex meeting update <meeting_id> --title "Updated Title" --agenda "New agenda" --idempotency-auto --json
```

## Destructive operations

Meeting cancel:

```bash
webex meeting cancel <meeting_id> --reason "Superseded" --confirm --idempotency-auto --json
```

Recurring series cancel:

```bash
webex meeting recurrence cancel <series_id> --from-occurrence 2026-01-20T15:00:00Z --confirm --idempotency-auto --json
```

## Invitee bulk input

Line mode:

```text
alice@example.test
bob@example.test
```

CSV mode:

```csv
email
alice@example.test
bob@example.test
```

Usage:

```bash
webex meeting invitee add <meeting_id> --invitees-file ./invitees.csv --invitees-file-format csv --idempotency-auto --json
```

## Templates and recurrence

Template list:

```bash
webex meeting template list --json
```

Template apply:

```bash
webex meeting template apply --template-id <template_id> --start 2026-01-10T15:00:00Z --end 2026-01-10T16:00:00Z --idempotency-auto --json
```

Recurrence create:

```bash
webex meeting recurrence create "Weekly Standup" --rrule "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO" --start 2026-01-12T15:00:00Z --duration 30 --idempotency-auto --json
```

Supported RRULE keys:

- `FREQ`
- `INTERVAL`
- `COUNT`
- `UNTIL`
- `BYDAY`
- `BYMONTHDAY`

Supported `FREQ` values:

- `DAILY`
- `WEEKLY`
- `MONTHLY`

## Failure modes

- capability errors return exit code `5`
- validation and state errors return exit code `2`
- mutation conflicts return exit code `8`
- disabled mutation policy returns `MUTATIONS_DISABLED`

## Recommended operator practice

1. Use `--json` for automation
2. Always set an explicit idempotency policy for retryable jobs
3. Use `--dry-run` before destructive schedule changes
4. Run with `--non-interactive` in automation so missing confirmations fail fast
