# Plan Readiness Checklist

Date: YYYY-MM-DD  
Plan: `<path-to-plan>`  
Owner: `<owner>`

---

## 1. Status Vocabulary

1. `draft`: plan exists but has unresolved design/specification gaps.
2. `reviewed`: plan has completed at least one independent review pass.
3. `implementation-ready`: all blocker gates are closed with traceable evidence.

---

## 2. Blocker Gates (Must All Be Closed)

| Gate | Requirement | Status (`open/closed`) | Evidence |
|---|---|---|---|
| Protocol lock | External integration mechanisms are explicit (transport, endpoints, auth, retries, fallback) | `open` | |
| Contract lock | JSON/output contracts and schema transitions are explicit and testable | `open` | |
| Error taxonomy lock | `error.code -> domain code -> exit integer -> retryable` mapping is complete | `open` | |
| Config lock | CLI flags, env vars, profile/global config precedence is explicit | `open` | |
| Storage lock | Local storage schema/versioning/migration/retention/rollback is explicit | `open` | |
| Capability lock | Upstream feature capability detection + fallback behaviors are explicit | `open` | |
| Platform lock | Cross-platform runtime behavior (Windows/Linux/macOS) is explicit | `open` | |
| Security lock | Redaction/encryption/key lifecycle/confirm guardrails are explicit | `open` | |
| Test lock | Unit/integration/e2e/perf/security/contract tests map to all major risks | `open` | |
| Delivery lock | Task board, critical path, capacity, and commit strategy are realistic | `open` | |
| Carryover lock | Open bugs from prior phase are fixed/mitigated/deferred with explicit risk | `open` | |

---

## 3. Traceability Matrix

Every major decision must map to at least one task and one test.

| Decision ID | Summary | Task IDs | Test Coverage | Status |
|---|---|---|---|---|
| D-01 |  |  |  | `open` |

---

## 4. Compatibility Delta Check

Compare plan expectations with current codebase behavior.

| Area | Current Behavior | Planned Behavior | Gap | Resolution |
|---|---|---|---|---|
| Meta envelope |  |  |  |  |
| Exit codes |  |  |  |  |
| Global options |  |  |  |  |
| Storage/migrations |  |  |  |  |

---

## 5. Independent Review Log

| Pass | Reviewer | Findings Count | Blocking Findings | Status |
|---|---|---:|---:|---|
| 1 |  |  |  | `open` |

---

## 6. Final Readiness Assertion

1. All blocker gates in section 2 are `closed`.
2. All rows in section 3 are `closed`.
3. Compatibility deltas in section 4 are resolved.
4. At least one independent review pass has zero blocking findings.
5. Plan status can be moved to `implementation-ready`.
