# Webex Meetings CLI Phase 1.1 Design

Date: 2026-03-02  
Status: Proposed  
Owner: Engineering + Product  
Depends on: `docs/2026-03-02-webex-meetings-cli-phase1-implementation-spec.md`

## 1. Why Phase 1.1 Exists

Phase 1.1 captures high-impact gaps and deferred work that should land after Phase 1 stabilization and before Phase 2 expansion.

Objectives:

1. Improve production reliability and security.
2. Reduce operational friction for CI/automation users.
3. Resolve ambiguities discovered during Phase 1 implementation.

## 2. Scope

### 2.1 In Phase 1.1

1. Auth hardening:
   - OAuth device flow support (optional alternative to raw token input).
   - Token refresh handling where supported.
   - Better auth diagnostics (`expired`, `revoked`, `insufficient_scope`).
2. Profile management baseline:
   - Multiple local profiles.
   - `webex profile list|use|show`.
3. Output and schema hardening:
   - Versioned JSON schema (`meta.schema_version`).
   - Strict compatibility tests for envelope.
4. Batch execution controls:
   - Concurrency option (`--concurrency`).
   - Explicit `--fail-fast` and `--continue-on-error` parity.
5. Download integrity improvements:
   - Optional checksum verification when upstream metadata exists.
   - resumable download design investigation (feature-flagged if partial support).
6. Observability:
   - Structured logs (`--log-format json|text`).
   - Correlation IDs and per-command timing.

### 2.2 Deferred beyond Phase 1.1

1. Free-text meeting search.
2. Transcript full-text search.
3. Speaker-segment tooling.
4. Webhook listener workflows.
5. Full host lifecycle operations.

## 3. UX Changes

### 3.1 New command group: profile

1. `webex profile list [--json]`
2. `webex profile use <profileName> [--json]`
3. `webex profile show [--json]`

Behavior:

1. `profile use` switches active profile pointer.
2. Missing profile returns `NOT_FOUND`.
3. `auth login` operates on active profile unless explicit `--profile`.

### 3.2 Auth enhancements

1. `webex auth login [--token <token>] [--device-flow] [--profile <name>] [--non-interactive]`
2. `--non-interactive` forbids device-flow prompts.
3. Clear error guidance for scope mismatch.

## 4. Data Model Changes

Profile model:

1. `name`
2. `active` flag (single active profile)
3. `site_url`
4. `default_tz`
5. `auth_method`
6. `created_at` / `updated_at`

Credential record:

1. `access_token` (secret store reference)
2. `refresh_token` (if available)
3. `expires_at`
4. `scopes`

## 5. Reliability and Performance Design

1. Concurrency:
   - Batch commands use bounded worker pool.
   - Default concurrency: 4.
   - Max concurrency: 16.
2. Backpressure:
   - Auto-throttle when 429 density crosses threshold.
3. Timeout policy:
   - command defaults remain from Phase 1
   - add per-command override flags where operationally needed.

## 6. Schema Versioning Strategy

1. Add `meta.schema_version`.
2. Start at `1.1`.
3. Minor-compatible additions allowed without major bump.
4. Breaking changes require major bump and migration note.

## 7. Security Improvements

1. Credential store must prefer OS secure storage.
2. Add preflight check warning if running in insecure fallback mode.
3. Redact secrets from:
   - logs
   - exception traces
   - debug HTTP dumps
4. Add secret scanning check in CI for fixtures and docs.

## 8. Test Plan Additions

1. Multi-profile switching tests.
2. Auth refresh/expiry tests.
3. JSON schema compatibility tests across releases.
4. Concurrency determinism and partial-failure tests.
5. Structured log validation tests.

## 9. Risks and Mitigations

1. Risk: OAuth device flow complexity and platform-specific UX.
   - Mitigation: introduce behind feature flag, keep token login default.
2. Risk: concurrency increases rate-limit pressure.
   - Mitigation: bounded pool + adaptive backoff.
3. Risk: multi-profile introduces accidental profile leakage in CI.
   - Mitigation: explicit active profile indicator in outputs and logs.

## 10. Deliverables

1. Updated command reference with profile/auth additions.
2. Schema v1.1 docs and fixtures.
3. Phase 1.1 release notes with migration impacts.
4. Hardening checklist completion report.

## 11. Phase 1.1 Exit Criteria

1. Multi-profile workflow is stable and tested.
2. Auth diagnostics are actionable and deterministic.
3. Batch concurrency is bounded and safe under rate limits.
4. JSON schema compatibility tests pass in CI.
5. No critical secrets exposure findings in security checks.
