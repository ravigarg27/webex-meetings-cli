# Webex Meetings CLI Roadmap

Date: 2026-03-02  
Status: Draft roadmap  
Owner: Product + Engineering

## 1. Roadmap Principles

1. Keep machine-safe contracts stable (`--json`, exit codes).
2. Ship vertical slices with test coverage, not broad partial features.
3. Prioritize participant workflows before host automation.
4. Preserve backward compatibility for script users.

## 2. Release Sequence

## Phase 1 (Current Delivery)

Theme: participant artifact retrieval baseline.

Planned outcomes:

1. Auth basics.
2. Meeting discovery and details.
3. Transcript lifecycle commands.
4. Recording list/status/download.
5. Deterministic JSON envelope + exit codes.

Success metrics:

1. >95% happy-path command success in smoke suite.
2. Stable command/JSON contracts.

## Phase 1.1 (Hardening + Operability)

Theme: reliability, security, and multi-profile foundation.

Planned outcomes:

1. Multi-profile support (`profile list/use/show`).
2. Auth improvements (device flow option, expiry/refresh diagnostics).
3. Batch concurrency controls.
4. Schema versioning and compatibility tests.
5. Structured logging and improved observability.

Success metrics:

1. Reduced auth-related support incidents.
2. Stable batch success under moderate rate limits.
3. No high-severity security findings in credential handling.

## Phase 2 (Discovery + Productivity)

Theme: faster finding and working with artifacts.

Planned outcomes:

1. Meeting free-text search.
2. Transcript full-text search.
3. Speaker-segment helpers.
4. Better filtering/sorting primitives.
5. Improved pagination ergonomics (auto-pagination options).

Success metrics:

1. Reduced time-to-artifact for users.
2. High search precision in integration tests.

## Phase 3 (Event-Driven + Host Workflows)

Theme: automation and lifecycle management.

Planned outcomes:

1. Webhook/event listener commands.
2. Host workflows:
   - create/update/cancel meetings
   - invitee management
   - recurring/template workflows
3. Automation-safe workflow orchestration primitives.

Success metrics:

1. Reliable event ingestion with retry/dead-letter strategy.
2. Host lifecycle commands match API semantics with deterministic errors.

## Phase 4 (Enterprise Scale + Governance)

Theme: enterprise-readiness and policy controls.

Planned outcomes:

1. Admin/audit output modes.
2. Policy-aware access diagnostics.
3. Bulk operations governance (quotas, approval hooks).
4. Compliance and retention visibility helpers.

Success metrics:

1. Successful pilot with enterprise org users.
2. Documented compliance and audit posture.

## 3. Cross-Phase Technical Investments

1. Contract testing for command and schema stability.
2. API adapter abstraction to isolate upstream API evolution.
3. Centralized error taxonomy.
4. Performance profiling for large date-range operations.
5. Documentation automation for CLI reference generation.

## 4. Dependencies and Assumptions

1. Upstream API access/scopes remain stable enough for participant artifacts.
2. Org/site policy constraints are discoverable via API responses.
3. OS keychain integrations are viable in supported environments.

## 5. Risks

1. Upstream API inconsistencies across tenants.
2. Rate-limit behavior under concurrent batch execution.
3. Contract drift between human output and JSON output.
4. Security risk from fallback credential storage.

## 6. Prioritized Backlog Snapshot

Priority P0:

1. Phase 1 implementation completion and stabilization.
2. Exit-code and JSON schema compatibility harness.
3. Credential storage hardening.

Priority P1:

1. Multi-profile support.
2. Batch concurrency and adaptive throttling.
3. Structured logging and telemetry.

Priority P2:

1. Free-text meeting and transcript search.
2. Speaker segment utilities.
3. Event listener MVP.

Priority P3:

1. Host lifecycle workflows.
2. Enterprise governance and compliance features.

## 7. Definition of Roadmap Health

1. Every phase has measurable success metrics.
2. Cross-phase technical debt is explicitly tracked.
3. Backward compatibility impacts are documented before release.
4. CI gates enforce schema/exit-code stability.
