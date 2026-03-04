# Phase 1.1 Contract Addendum

Date: 2026-03-04  
Status: Approved

## Scope Lock

Phase 1.1 contract scope is locked to:

1. Profile-scoped execution with explicit profile lifecycle commands.
2. Dual auth methods: PAT + OAuth device flow.
3. OAuth refresh lifecycle and invalid-state handling.
4. Transcript batch concurrency, fail-fast semantics, and adaptive throttling.
5. Download integrity checks (optional checksum verification when metadata exists).
6. JSON envelope/exit-code compatibility with schema version `1.1`.
7. Structured logging + correlation IDs + command timing metadata.
8. Centralized redaction and CI-strict fallback credential policy.

## Compatibility Contract

1. Top-level JSON envelope keys are immutable: `ok`, `command`, `data`, `warnings`, `error`, `meta`.
2. Required `meta` keys for schema `1.1`: `request_id`, `timestamp`, `cli_version`, `schema_version`, `duration_ms`.
3. Exit-code matrix is locked by `tests/contracts/fixtures/exit_code_matrix_v1_1.json`.
4. Any intentional incompatible change requires a schema-major exception approval.

## Deletion Semantics

1. `profile delete` is local-only in Phase 1.1.
2. Active profile deletion is blocked.
3. Server-side OAuth revocation is deferred beyond Phase 1.1.
