# Phase 1.1 Implementation Plan and Task Board

> Planning and execution tracker. Phase 1.1 implementation is complete.

**Goal:** Deliver Phase 1.1 hardening and operability for `webex-meetings-cli` with profile support, dual auth modes (PAT + OAuth device flow), batch reliability controls, contract governance, and security/observability upgrades.

**Architecture:** Extend the existing command/client/config/error layers without breaking Phase 1 command contracts. Introduce profile-scoped state and OAuth lifecycle in a backward-compatible way, then enforce JSON/exit-code compatibility at RC/GA through CI gates.

**Tech Stack:** Python 3.11+, Typer, httpx, pytest.

---

## Locked Design Decisions

1. Profile precedence: `--profile` > `WEBEX_PROFILE` > active profile.
2. Existing installs auto-migrate to profile `default` with idempotent migration.
3. Phase 1.1 includes both PAT flow and OAuth device flow.
4. Batch concurrency defaults: `min=1`, `default=4`, `max=16`.
5. Schema policy: flexible pre-RC, freeze at RC, strict at GA.
6. OAuth storage: `access_token`, `refresh_token`, `expires_at`, `scopes` with strict redaction/profile isolation.
7. Refresh behavior: proactive refresh at <=120s to expiry + 401 fallback; single-flight per profile; no refresh for PAT.
8. `profile use` fails for missing profile (explicit create required).
9. Profile deletion is safety-constrained (active profile cannot be deleted directly).
10. Auth method contract: default PAT path; explicit `--oauth-device-flow`; mutually exclusive token source inputs.
11. OAuth device flow is fully enabled immediately (no feature flag gate).
12. Login performs baseline capability checks (identity + meetings); artifact capability checks remain lazy.
13. Credential fallback policy defaults to `ci_strict`.
14. OAuth config resolution order: CLI flags > env vars > config.
15. Terminal refresh failure marks profile auth invalid (no auto-clear); explicit re-login required.
16. Profile naming: strict validation with reserved-name blocking and case-insensitive uniqueness.
17. CI contract gates: non-blocking pre-RC, blocking at RC, strict at GA.
18. `--profile` is a global option available to all command groups (auth + data commands), not auth-only.
19. `profile create` interface:
   1. Required: `<name>`.
   2. Optional: `--default-tz`, `--site-url`.
   3. Existing name (case-insensitive) returns `VALIDATION_ERROR`.
20. `profile show` interface:
   1. Default shows active profile.
   2. Optional `<name>` shows named profile.
   3. Credential material is never displayed.
21. `profile delete` performs local credential/config removal only in 1.1 (no server-side OAuth token revocation).
22. `--fail-fast` with concurrency semantics:
   1. Stop queueing new items on first terminal failure.
   2. In-flight workers finish current item only.
   3. Exit code is the first terminal failure code.
23. Download integrity improvements remain in Phase 1.1:
   1. Optional checksum verification when metadata is available.
   2. Resumable download is investigation + design output, not guaranteed implementation.
24. `meta.schema_version` is explicitly bumped from `1.0` to `1.1` at RC cutover.
25. OAuth device-flow protocol behavior is explicitly specified in this plan (polling, error mapping, configuration).

---

## Command Interface Specifications

### Profile Commands

1. `webex profile create <name> [--default-tz <iana_tz>] [--site-url <https_url>] [--json]`
   1. `<name>` must satisfy locked naming rules.
   2. `--site-url` must be `https` when provided.
   3. Duplicate profile name (case-insensitive) returns `VALIDATION_ERROR`.
2. `webex profile list [--json]`
   1. Returns all profiles and active marker.
3. `webex profile show [<name>] [--json]`
   1. No `<name>` means active profile.
   2. Includes profile metadata only (never secrets).
4. `webex profile use <name> [--json]`
   1. Missing profile returns `NOT_FOUND`.
5. `webex profile delete <name> [--json]`
   1. Cannot delete active profile.
   2. Deletes local scoped credentials/settings/metadata only.

### Global Profile Option

1. `--profile` is available on all command groups (`auth`, `meeting`, `transcript`, `recording`, `profile` where relevant).
2. Effective profile resolution order remains:
   1. `--profile`
   2. `WEBEX_PROFILE`
   3. active profile pointer.

---

## OAuth Device Flow Protocol Contract

1. Endpoint configuration:
   1. Device authorization endpoint, token endpoint, and client id are configurable.
   2. Resolution order is flags > env > config.
   3. Defaults are provided by app config constants and must match official Webex docs.
2. Polling behavior:
   1. Default poll interval: `5s`.
   2. Configurable bounds: `2..30s`.
   3. Max wait timeout default: `600s`.
3. Required OAuth error handling:
   1. `authorization_pending`: continue polling.
   2. `slow_down`: increase polling interval by +5s for subsequent polls.
   3. `access_denied`: fail with `AUTH_INVALID` and actionable message.
   4. `expired_token`: fail with `AUTH_INVALID` and remediation to restart login.
4. Non-interactive behavior:
   1. Device flow with non-interactive mode must fail fast and never prompt.
5. Requested scopes:
   1. Default scope set is explicit and documented in CLI help and docs.
   2. Scope override support is optional in 1.1 and may be deferred.

---

## Batch Concurrency and Fail-Fast Semantics

1. In continue mode:
   1. Process all queued items and aggregate per-item status.
2. In fail-fast mode:
   1. First terminal failure stops queue admission.
   2. In-flight workers finish current item.
   3. Remaining queued items are skipped with reason `FAIL_FAST_ABORTED`.
   4. Command exits with first terminal failure code.
3. JSON summary contract:
   1. Must preserve existing totals and `results[]` schema.

---

## Task Board

| Status | ID | Sprint | Lane | Owner | Task | Depends On | Estimate | Definition of Done |
|---|---|---:|---|---|---|---|---:|---|
| `done` | P11-GOV-01 | 0 | Governance | `@owner-platform` | Write Phase 1.1 contract addendum capturing all locked decisions | None | 0.5d | Contract doc merged and linked from roadmap/design docs |
| `done` | P11-GOV-02 | 0 | Governance | `@owner-platform` | Define RC freeze date and release branch policy | P11-GOV-01 | 0.5d | RC policy documented and acknowledged by maintainers |
| `done` | P11-GOV-03 | 0 | Governance | `@owner-platform` | Define schema-major exception workflow for intentional breaking changes | P11-GOV-01 | 0.5d | Exception workflow documented and test-gated |
| `done` | P11-PROF-01 | 1 | Profiles | `@owner-config` | Add profile registry model + active profile pointer | P11-GOV-01 | 1.5d | Profile registry persists and active pointer resolves correctly |
| `done` | P11-PROF-02 | 1 | Profiles | `@owner-config` | Make settings and credential resolution profile-scoped | P11-PROF-01 | 1.5d | Switching profile switches effective settings and credentials |
| `done` | P11-PROF-03 | 1 | Profiles | `@owner-cli` | Add global profile resolution plumbing for all command groups | P11-PROF-02 | 1.0d | `--profile` precedence works consistently for auth and data commands |
| `done` | P11-MIG-01 | 1 | Profiles | `@owner-config` | Implement one-time idempotent auto-migration to `default` profile | P11-PROF-02 | 1.0d | Existing installs upgrade automatically without data loss |
| `done` | P11-MIG-02 | 1 | Profiles | `@owner-config` | Add migration rollback path + backup marker | P11-MIG-01 | 0.5d | Failed migration restores prior state and emits actionable error |
| `done` | P11-VAL-01 | 1 | Profiles | `@owner-config` | Add profile name validator + reserved name protections | P11-PROF-01 | 0.5d | Invalid/reserved names rejected consistently across commands |
| `done` | P11-TEST-01 | 1 | QA | `@owner-qa` | Add unit tests for precedence, migration, and naming rules | P11-MIG-02, P11-VAL-01 | 1.0d | Tests cover edge cases and pass in CI |
| `done` | P11-CMD-01 | 2a | Profiles | `@owner-cli` | Add `profile create|list|show|use|delete` commands | P11-PROF-02, P11-VAL-01 | 1.5d | Create/show/use/delete interfaces match command spec (defaults, duplicates, visibility) in human and JSON modes |
| `done` | P11-CMD-02 | 2a | Profiles | `@owner-cli` | Enforce profile deletion safety contract (active-profile protection + deterministic errors) | P11-CMD-01 | 0.5d | `profile delete` safety rules match locked decisions in all modes |
| `done` | P11-AUTH-01 | 2b | Auth | `@owner-auth` | Add `--profile` support to `auth login|logout|whoami` | P11-PROF-03 | 1.0d | Auth commands honor explicit/env/active precedence |
| `done` | P11-AUTH-02 | 2b | Auth | `@owner-auth` | Add PAT + OAuth device-flow method selection and exclusivity checks | P11-AUTH-01 | 1.5d | Deterministic login method behavior with clear validation errors |
| `done` | P11-AUTH-03 | 2b | Auth | `@owner-auth` | Normalize auth diagnostics (`expired`, `revoked`, `insufficient_scope`, `invalid`) | P11-AUTH-02 | 1.0d | JSON error details include stable auth cause fields |
| `done` | P11-AUTH-04 | 2b | Auth | `@owner-auth` | Implement OAuth config resolution order (flags > env > config) + validation | P11-AUTH-02 | 1.0d | Device flow fails fast with actionable config errors; precedence is deterministic |
| `done` | P11-AUTH-05 | 2b | Auth | `@owner-auth` | Implement device-flow non-interactive behavior, timeout, and cancel mapping | P11-AUTH-02 | 1.0d | Non-interactive mode does not prompt; timeout/cancel paths return stable errors |
| `done` | P11-TEST-02 | 2b | QA | `@owner-qa` | Add integration tests for auth method routing, profile isolation, deletion safety, OAuth config precedence, and global profile propagation | P11-AUTH-05, P11-AUTH-04, P11-AUTH-03, P11-CMD-02, P11-PROF-03 | 1.5d | Cross-profile and auth-edge behavior verified under CLI tests |
| `done` | P11-OAUTH-01 | 3 | Auth | `@owner-auth` | Persist OAuth token bundle per profile (`access`, `refresh`, `expires_at`, `scopes`) | P11-AUTH-02 | 1.0d | OAuth sessions survive process restart per profile |
| `done` | P11-OAUTH-02 | 3 | Auth | `@owner-auth` | Implement refresh lifecycle (proactive + 401 fallback + single-flight) | P11-OAUTH-01 | 1.5d | No refresh stampede and request replay works once |
| `done` | P11-OAUTH-03 | 3 | Auth | `@owner-auth` | Implement terminal refresh failure invalid-state behavior | P11-OAUTH-02 | 0.5d | Profile marked invalid; commands fail with remediation |
| `done` | P11-OAUTH-04 | 3 | Auth | `@owner-auth` | Implement OAuth token storage layout in CredentialStore (keyring + metadata, fallback handling) | P11-OAUTH-01 | 1.0d | Keyring stores secret material; metadata stores non-secrets; fallback encrypts secrets per platform and is tested |
| `done` | P11-BATCH-01 | 3 | Reliability | `@owner-cli` | Add transcript batch bounded worker pool (`--concurrency`) | P11-GOV-01 | 2.0d | Batch runs concurrently while preserving result schema |
| `done` | P11-BATCH-02 | 3 | Reliability | `@owner-cli` | Add adaptive throttling/backpressure for 429/5xx bursts | P11-BATCH-01 | 1.5d | Under throttling, failure rate and retry storms are bounded |
| `done` | P11-BATCH-03 | 3 | Reliability | `@owner-cli` | Implement fail-fast semantics for concurrent workers (`FAIL_FAST_ABORTED`, first-failure exit) | P11-BATCH-01 | 1.0d | Fail-fast behavior is deterministic and documented |
| `done` | P11-SAFE-01 | 3 | Reliability | `@owner-client` | Add pagination loop/no-progress detection guards | P11-BATCH-01 | 0.5d | Repeated token/cycle exits with deterministic error |
| `done` | P11-TEST-03 | 3 | QA | `@owner-qa` | Add reliability tests for throttling, fail-fast concurrency semantics, and refresh race safety | P11-BATCH-03, P11-BATCH-02, P11-OAUTH-03, P11-SAFE-01 | 1.5d | Stress-like tests pass and are repeatable |
| `done` | P11-OBS-01 | 4 | Observability | `@owner-platform` | Add `--log-format text|json` + env control | P11-GOV-01 | 1.0d | Log format is configurable and stable |
| `done` | P11-OBS-02 | 4 | Observability | `@owner-platform` | Add request/correlation IDs and command timing fields | P11-OBS-01 | 1.0d | Each command emits traceable metadata |
| `done` | P11-SEC-01 | 4 | Security | `@owner-security` | Add centralized redaction for logs/errors and tests | P11-OBS-01 | 1.0d | Token-like material never appears in logs/errors |
| `done` | P11-SEC-02 | 4 | Security | `@owner-security` | Enforce `ci_strict` credential fallback behavior | P11-AUTH-02, P11-SEC-01 | 1.0d | CI/non-interactive fallback policy enforced and tested |
| `done` | P11-DL-01 | 4 | Reliability | `@owner-client` | Add optional checksum verification for downloads when upstream checksum metadata exists | P11-BATCH-01 | 1.0d | Checksum verification can be enabled and failures are actionable |
| `done` | P11-DL-02 | 4 | Reliability | `@owner-client` | Investigate resumable download support and publish design decision note | P11-DL-01 | 0.5d | Documented go/no-go and implementation constraints for resumable downloads |
| `done` | P11-CON-01 | 5 | Contracts | `@owner-platform` | Add JSON envelope compatibility fixtures for all commands | P11-GOV-03 | 1.5d | Compatibility test suite captures all command envelopes |
| `done` | P11-CON-02 | 5 | Contracts | `@owner-platform` | Add exit-code compatibility matrix tests | P11-CON-01 | 1.0d | Exit-code drift is detected automatically |
| `done` | P11-CON-03 | 5 | Contracts | `@owner-platform` | Bump `meta.schema_version` to `1.1` at RC cut and update fixtures/docs | P11-CON-01, P11-GOV-02 | 0.5d | Schema version and fixtures are aligned at RC |
| `done` | P11-CI-01 | 5 | Contracts | `@owner-platform` | Configure CI gate modes (warn pre-RC, block RC/GA) | P11-CON-01, P11-CON-02, P11-GOV-02 | 1.0d | CI behavior matches release phase policy |
| `done` | P11-DOC-01 | 5 | Docs | `@owner-docs` | Update README, auth/profile docs, migration and release notes | P11-CMD-01, P11-AUTH-03, P11-OAUTH-03, P11-CI-01, P11-CON-03, P11-DL-02 | 1.0d | Documentation matches shipped CLI behavior |
| `done` | P11-REL-01 | 5 | Release | `@owner-platform` | Execute Phase 1.1 release checklist + Go/No-Go review | P11-TEST-03, P11-SEC-02, P11-CI-01, P11-DOC-01, P11-CON-03 | 0.5d | Release readiness approved with checklist evidence |

---

## Critical Path

1. Governance decisions codified (`P11-GOV-*`).
2. Profile foundation, global propagation, and migration (`P11-PROF-*`, `P11-MIG-*`).
3. Profile command interfaces (`P11-CMD-*`) then auth method integration and OAuth lifecycle (`P11-AUTH-*`, `P11-OAUTH-*`).
4. Batch reliability hardening (`P11-BATCH-*`, `P11-SAFE-01`) with deterministic fail-fast semantics.
5. Observability/security/download-integrity work (`P11-OBS-*`, `P11-SEC-*`, `P11-DL-*`).
6. Contract CI gates and schema cutover (`P11-CON-*`, `P11-CI-01`).
7. Documentation and release (`P11-DOC-01`, `P11-REL-01`).

---

## Acceptance Gates Before RC

1. Profile isolation validated in unit + integration + e2e.
2. OAuth refresh behavior stable under concurrent commands.
3. Batch concurrency stable under throttling tests and fail-fast semantics.
4. Redaction tests prove no secret leakage.
5. JSON envelope and exit-code compatibility suites are green.
6. `meta.schema_version` is bumped to `1.1` at RC and reflected in fixtures/docs.
7. Migration is idempotent and rollback-tested.
8. Download integrity tasks are closed (`P11-DL-01` implemented, `P11-DL-02` documented outcome).

---

## Commit Strategy

This plan follows repository commit conventions in `docs/2026-03-03-implementation-commit-strategy.md`.

1. One commit per task ID or tightly coupled pair (`feature + tests`).
2. Commit message format:
   1. `feat:` for command/client/config behavior changes.
   2. `fix:` for contract or bug corrections discovered during implementation.
   3. `test:` for test-only additions.
   4. `docs:` for documentation-only updates.
3. No mixed-scope commits (for example, do not combine profile migration and batch concurrency).
4. Every behavior commit must include tests in the same commit or the immediately following commit.
5. No amend/force-push during review without explicit approval.

### Planned Commit Sequence

1. Sprint 0: `docs: lock phase 1.1 contracts and governance policy`
2. Sprint 1: `feat: add profile model, scoped resolution, and global profile plumbing`
3. Sprint 1: `feat: add idempotent default-profile migration with rollback`
4. Sprint 1: `test: add profile precedence and migration tests`
5. Sprint 2a: `feat: add profile command group and deletion safety`
6. Sprint 2b: `feat: add auth profile routing and dual-method login selection`
7. Sprint 2b: `feat: add oauth config precedence, polling/error mapping, and non-interactive semantics`
8. Sprint 2b: `test: add auth/profile integration coverage`
9. Sprint 3: `feat: persist oauth session bundle and refresh lifecycle`
10. Sprint 3: `feat: add transcript batch concurrency, adaptive throttling, and fail-fast semantics`
11. Sprint 3: `fix: add pagination no-progress guard`
12. Sprint 3: `test: add reliability and refresh race tests`
13. Sprint 4: `feat: add structured logging, correlation ids, and timing`
14. Sprint 4: `fix: enforce ci_strict fallback policy and redaction controls`
15. Sprint 4: `feat: add optional checksum verification and resumable-download decision note`
16. Sprint 4: `test: add redaction, fallback policy, and checksum tests`
17. Sprint 5: `test: add json envelope and exit-code compatibility suites`
18. Sprint 5: `chore: bump schema_version to 1.1 and align fixtures`
19. Sprint 5: `ci: enforce pre-rc/rc/ga contract gate modes`
20. Sprint 5: `docs: publish phase 1.1 user/admin migration and auth docs`

---

## Detailed Test Matrix

### Unit Tests

1. Profile resolution precedence: `--profile` vs `WEBEX_PROFILE` vs active profile.
2. Global profile propagation across data command contexts.
3. Profile name validation and reserved-name rejection.
4. Profile create/show interface defaults and duplicate behavior.
5. Migration idempotency marker behavior.
6. Migration rollback on partial failure.
7. Auth method exclusivity checks (PAT inputs with OAuth flag).
8. OAuth config precedence resolution (flags > env > config).
9. Device flow non-interactive validation path.
10. Device flow poll interval bounds and timeout behavior.
11. OAuth error mapping (`authorization_pending`, `slow_down`, `access_denied`, `expired_token`).
12. OAuth token refresh threshold check (`<=120s`).
13. Refresh single-flight locking behavior.
14. Terminal refresh failure state transition.
15. Pagination loop/no-progress detection.
16. Concurrency bounds enforcement (`1..16`).
17. Fail-fast queue admission and `FAIL_FAST_ABORTED` result mapping.
18. Redaction sanitizer behavior for known secret patterns.
19. Contract fixture parser/validator logic.

### Integration Tests (mocked upstream)

1. Cross-profile auth isolation (`profile A` credentials never used for `profile B`).
2. PAT login baseline capability probe success/failure mapping.
3. OAuth device flow success path and timeout path.
4. OAuth `slow_down` handling adjusts polling interval.
5. OAuth refresh on near-expiry before request dispatch.
6. OAuth refresh on 401 fallback with one replay.
7. Refresh terminal failure produces invalid profile auth state.
8. Batch concurrency under moderate 429 density with adaptive backoff.
9. Fail-fast with concurrency stops queueing new items and preserves deterministic exit behavior.
10. Batch result schema remains stable under concurrent failures.
11. Pagination cycle returns deterministic error (no infinite loop).
12. `ci_strict` fallback behavior in non-interactive mode.
13. Redaction verification for logs and error payloads.
14. Optional checksum verification pass/fail behavior.

### E2E / CLI Smoke

1. Profile lifecycle: create, use, show, delete (with safety constraints).
2. PAT flow: login, whoami, meeting list.
3. OAuth flow: login, whoami, transcript/recording command execution.
4. Profile switching between PAT and OAuth profiles in one run.
5. Data commands with explicit `--profile` override active profile.
6. Transcript batch with `--concurrency` and stable summary output.
7. `--fail-fast` with concurrency semantics under mixed success/failure.
8. JSON envelope snapshots for representative commands.

### Contract and CI Gate Tests

1. JSON envelope compatibility fixtures for all command groups.
2. Exit-code matrix completeness and immutability checks.
3. RC gate mode behavior (warn vs block) validation in CI config.
4. `schema_version=1.1` cutover check at RC.

### Security Tests

1. No token/refresh token leakage in logs at all log levels.
2. No token-like leakage in error `details`.
3. Profile deletion removes scoped credentials/settings correctly (local-only semantics).
4. Fallback credential policy behavior across local interactive vs CI modes.
5. OAuth refresh token encryption/storage behavior is correct per backend.

---

## External Evaluation Checklist

1. All 25 locked decisions are mapped to at least one task and one test category.
2. Every high-risk behavior (migration, OAuth refresh, concurrency, fail-fast semantics, contract gates, redaction, storage handling) has explicit acceptance criteria.
3. Task dependencies form a valid execution graph (no circular dependencies).
4. Commit sequencing is explicit and aligns with repository strategy.
5. Contract governance is phase-aware (pre-RC vs RC vs GA).
6. Plan clearly states this is planning-only and contains no implementation claims.
7. Release readiness has explicit go/no-go task and criteria.

---

## Risk Register

1. **Risk:** OAuth device flow edge-case instability across environments.
   1. **Mitigation:** `P11-AUTH-05`, `P11-TEST-02`, explicit timeout/cancel/non-interactive semantics.
2. **Risk:** Migration data loss or partial state.
   1. **Mitigation:** `P11-MIG-02` rollback path + backup marker + idempotency tests.
3. **Risk:** Token leakage in logs/errors due to new observability work.
   1. **Mitigation:** `P11-SEC-01` centralized redaction and security tests.
4. **Risk:** Concurrency increases rate-limit failures.
   1. **Mitigation:** `P11-BATCH-02` adaptive throttling + `P11-TEST-03` reliability tests.
5. **Risk:** Contract drift during rapid iteration.
   1. **Mitigation:** `P11-CON-01`, `P11-CON-02`, and `P11-CI-01` phase-aware contract gates.
6. **Risk:** Profile cross-contamination in auth/session use.
   1. **Mitigation:** profile precedence contract + cross-profile integration tests (`P11-TEST-02`).
7. **Risk:** Download corruption or integrity uncertainty.
   1. **Mitigation:** `P11-DL-01` checksum verification and `P11-DL-02` resumable-download decision note.

---

## Out of Scope for Phase 1.1

1. Meeting/recording/transcript search feature expansion (Phase 2).
2. Host lifecycle APIs (`meeting create|update|cancel`) (Phase 3+).
3. Webhook listener and event-driven orchestration (Phase 3+).
4. Enterprise governance/compliance command surfaces (Phase 4).

---

## Current State

1. Phase 1.1 planning: externally reviewed and accepted.
2. Implementation: completed.
3. Task statuses: all `done`.
4. This document is the authoritative Phase 1.1 execution record.
5. External evaluator gaps (2-10) are integrated and closed in shipped implementation.

---

## Plan Review Log

### Review Pass 1
**Gaps found:** unclear dependency order, no migration rollback task, no measurable acceptance gates.  
**Fixes:** added dependency graph in task board, `P11-MIG-02`, explicit RC acceptance gates.

### Review Pass 2
**Gaps found:** reliability edge cases were under-specified (pagination cycles, throttling behavior).  
**Fixes:** added `P11-SAFE-01`, `P11-BATCH-02`, and reliability-focused test task `P11-TEST-03`.

### Review Pass 3
**Gaps found:** contract governance and CI enforcement were implicit.  
**Fixes:** added `P11-CON-01`, `P11-CON-02`, and `P11-CI-01` with phase-aware gating policy.

### Review Pass 4
**Gaps found:** security behavior and release closure criteria were incomplete.  
**Fixes:** added `P11-SEC-01`, `P11-SEC-02`, and final release/doc tasks (`P11-DOC-01`, `P11-REL-01`).

### Review Pass 5
**Gaps found:** two locked decisions were not fully represented in tasks (OAuth config precedence and device-flow non-interactive semantics), and profile delete safety was not isolated as its own deliverable.  
**Fixes:** added `P11-CMD-02`, `P11-AUTH-04`, `P11-AUTH-05`, and expanded `P11-TEST-02` coverage/dependencies.

### Review Pass 6
**Gaps found (external review):** profile command interface ambiguity, missing download-integrity scope handling, missing OAuth protocol detail, unspecified fail-fast + concurrency interaction, unclear global `--profile` propagation, unspecified OAuth storage mechanics, Sprint 2 overload, missing profile-delete revocation policy decision, missing explicit schema bump task.  
**Fixes:** added command interface specs, OAuth protocol contract, fail-fast semantics section, global profile decision + `P11-PROF-03`, OAuth storage task `P11-OAUTH-04`, Sprint split `2a/2b`, local-only deletion decision, download-integrity tasks `P11-DL-*`, and schema bump task `P11-CON-03`.

### Final Confidence Check
No unresolved blocking design ambiguity remains. High-risk reviewer attack areas (auth ambiguity, migration safety, secret leakage, contract drift, rate-limit stability, fail-fast determinism, and download integrity) are explicitly covered by decisions, tasks, and tests.
