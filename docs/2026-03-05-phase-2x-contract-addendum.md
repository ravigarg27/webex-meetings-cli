# Phase 2X Contract Addendum

Status: implemented

## Scope

Phase 2X extends the CLI in three areas:

1. Discovery and transcript indexing
2. Event ingress and queue-backed listeners
3. Host workflow mutations

## Schema progression

1. Schema `1.2` introduced:
   1. `meta.profile`
   2. `meta.command_mode`
   3. discovery and event command additions
2. Schema `1.3` introduced:
   1. host workflow mutations
   2. idempotency and dry-run contracts
   3. deterministic capability/state/conflict error families

Current runtime schema version: `1.3`

## Envelope contract

All JSON commands emit:

- top-level keys: `ok`, `command`, `data`, `warnings`, `error`, `meta`
- meta keys: `request_id`, `timestamp`, `cli_version`, `schema_version`, `duration_ms`, `profile`, `command_mode`

`command_mode` is one of:

- `read`
- `listen`
- `mutation`

## Error taxonomy additions

New domain families locked in Phase 2X:

- `CAPABILITY_ERROR`
- `STATE_ERROR`
- `CONFLICT_ERROR`

Deterministic feature error codes are fixture-locked in `tests/contracts/fixtures/error_codes_v1_3.json`.

## Mutation contract

Mutation responses include:

- `operation_id`
- `idempotency_key`
- `state`
- `dry_run`
- `dry_run_mode`
- `validation`
- `warnings`

Dry-run state is `dry_run_validated`.

Idempotent replay state is `no_op`.

Completed mutation state is `completed`.

## Local store contract

Phase 2X introduces profile-scoped stores:

- `events/<profile>/queue.db`
- `events/<profile>/dedupe.db`
- `events/<profile>/dlq.db`
- `events/<profile>/checkpoints.db`
- `search/<profile>/transcript-index.db`
- `mutations/<profile>/idempotency-cache.json`

Event and search meta stores use version marker `1.2`.
