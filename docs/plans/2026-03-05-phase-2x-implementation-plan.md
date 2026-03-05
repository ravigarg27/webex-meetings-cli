# Phase 2 Master Plan (Combined Phase 2 + Phase 3)

Date: 2026-03-05  
Status: implementation-ready  
Owner: Product + Engineering  
Supersedes: high-level roadmap sections for Phase 2 and Phase 3

---

## 0. Readiness Gate

This plan is evaluated using [plan-readiness-checklist.md](C:\Users\ravigar\Projects\webex-meetings-cli\docs\plans\plan-readiness-checklist.md).

### 0.1 Blocking readiness table

| Gate | Required outcome | Status | Evidence |
|---|---|---|---|
| Protocol lock | Event ingestion mechanism is concrete and implementable | `closed` | Sections 3.42, 4.3, 4.4, 4.6, 10 (`P2X-EVT-08..11`) |
| Contract lock | Schema/meta and dry-run contracts are explicit and staged | `closed` | Sections 5.2, 5.3, 15; task `P2X-OBS-01` moved early |
| Error taxonomy lock | `error.code -> DomainCode -> exit int -> retryable` mapping is explicit | `closed` | Section 5.4, tasks `P2X-CON-03/04/05` |
| Config lock | Global flag/env/profile/global/default precedence is complete | `closed` | Sections 3.37, 8.1, tasks `P2X-CFG-*` |
| Storage lock | Store versioning, migration rollback, retention, sqlite mode are explicit | `closed` | Sections 7.4, 7.5, tasks `P2X-STR-*` |
| Capability lock | Capability detection defined for transcript/templates/recurrence/events/invitees | `closed` | Section 3.43, tasks `P2X-CAP-*` |
| Platform lock | Windows/Linux/macOS signal/runtime behavior is explicit | `closed` | Section 4.6 (shutdown), task `P2X-EVT-11` |
| Security lock | Encryption key lifecycle, redaction, non-interactive safety are explicit | `closed` | Sections 8, 8.2, tasks `P2X-SRCH-05/08`, `P2X-HOST-*` |
| Test lock | All risky lanes mapped to unit/integration/e2e/perf/security/contract tests | `closed` | Section 12 |
| Delivery lock | Task board capacity and critical path are realistic | `closed` | Section 10 (Sprint split), section 11 |
| Carryover lock | Prior known bugs are fixed or actively guarded by preflight checks | `closed` | Section 10 (`P2X-PRE-*`) |

### 0.2 Pre-implementation stop rule

No implementation work may start unless all rows in section 0.1 remain `closed`.

### 0.3 Decision traceability matrix

| Decision | Task IDs | Test coverage sections |
|---|---|---|
| Event transport + queue lock | `P2X-EVT-08`, `P2X-EVT-09`, `P2X-EVT-10`, `P2X-EVT-11`, `P2X-STR-03` | 12.2 (5, 15, 18, 19), 12.3 (3, 10), 12.5 (3, 8) |
| Meta envelope lock | `P2X-OBS-01`, `P2X-CON-01` | 12.6 (1, 6) |
| Error taxonomy lock | `P2X-CON-03`, `P2X-CON-04` | 12.1 (15, 21), 12.6 (2, 5) |
| Filter DSL + case-sensitivity lock | `P2X-QRY-01`, `P2X-QRY-04`, `P2X-SRCH-06` | 12.1 (1, 18, 22), 12.2 (3) |
| Idempotency + dry-run lock | `P2X-HOST-09`, `P2X-HOST-10`, `P2X-HOST-02`, `P2X-HOST-03`, `P2X-HOST-06`, `P2X-HOST-07` | 12.1 (11), 12.2 (10, 12, 17) |
| Replay override lock | `P2X-EVT-03`, `P2X-EVT-04`, `P2X-EVT-07` | 12.2 (5, 19), 12.3 (4) |
| Storage + migration lock | `P2X-STR-01`, `P2X-STR-02`, `P2X-STR-03` | 12.1 (17), 12.4 (5), 12.5 (5, 6) |
| Local index key lifecycle lock | `P2X-SRCH-05`, `P2X-SRCH-08` | 12.5 (2, 7), 12.3 (7) |
| RRULE + invitee format lock | `P2X-HOST-11`, `P2X-HOST-12`, `P2X-HOST-05`, `P2X-HOST-07` | 12.1 (19, 20), 12.2 (8, 9) |

### 0.4 Compatibility delta check (current code vs target)

| Area | Current baseline | Phase 2X target | Resolution task |
|---|---|---|---|
| JSON meta | `profile` and `command_mode` are not universally emitted | required in schema 1.2+ outputs | `P2X-OBS-01` |
| Error mapping | no mapping for new capability/state/conflict families | explicit taxonomy with fixed exit/retry mapping | `P2X-CON-03`, `P2X-CON-04` |
| Non-interactive flags | auth has local `--non-interactive` behavior | one global canonical behavior | `P2X-PRE-02` |
| Event ingest | no ingress transport in current CLI | explicit webhook ingress and registration paths | `P2X-EVT-08`, `P2X-EVT-09` |
| Local stores | no Phase 2X store versioning model | explicit versioned/migrated stores | `P2X-STR-01`, `P2X-STR-02`, `P2X-STR-03` |

---

## 1. Objective

Deliver a single implementation program that combines:

1. **Phase 2 (Discovery + Productivity)**
2. **Phase 3 (Event-Driven + Host Workflows)**

This combined program is named **Phase 2X**.

Phase 2X goal:

1. Reduce time-to-artifact through first-class search and filtering.
2. Enable automation-safe event-driven workflows.
3. Add host lifecycle operations with deterministic behavior and strong safety controls.
4. Keep machine contracts stable (`--json`, exit code taxonomy, schema versioning policy).

---

## 2. Scope Merge Decision

### 2.1 What is merged now

1. Phase 2 discovery features are fully included.
2. Phase 3 event listener and orchestration primitives are fully included.
3. Phase 3 host workflows are included with a strict safety model (`--dry-run`, idempotency keys, explicit confirmation controls for destructive operations).

### 2.2 Why merge is feasible

1. Shared infrastructure overlaps heavily:
   1. query/filter grammar
   2. pagination engine
   3. normalization and contract layers
   4. observability and correlation IDs
2. Existing Phase 1.1 foundation already provides:
   1. profile-scoped credentials and OAuth refresh
   2. concurrency controls and backoff patterns
   3. schema contract and CI governance
3. Splitting into separate phases would duplicate architecture work and prolong integration risk.

### 2.3 What stays out of scope

1. Phase 4 enterprise governance features (approval hooks, compliance reporting suites, enterprise policy controls).
2. Multi-region active-active event consumers.
3. Third-party sink plugins beyond built-in `stdout`/`jsonl`/`file` sinks.

---

## 3. Locked Design Decisions

1. Profile precedence remains: `--profile` > `WEBEX_PROFILE` > active profile.
2. All new command groups support `--json` with unchanged top-level envelope keys.
3. Search commands are **read-only** and never mutate remote state.
4. Host mutation commands require explicit operation options; no implicit defaults for destructive behavior.
5. `meeting cancel` defaults to safe mode requiring either `--confirm` or `--yes` in non-interactive contexts.
6. Mutation commands support idempotency keys with explicit policy:
   1. required in non-interactive and batch contexts
   2. optional in interactive single-shot mode (CLI may generate and print one)
   3. generated keys are never reused implicitly across separate invocations.
7. Event ingestion is at-least-once with deduplication by event ID and source timestamp window.
8. Event dead-letter queue (DLQ) is mandatory for non-transient processing failures.
9. Retry policy for transient event processing failures: exponential backoff with jitter and bounded attempts.
10. Event listener state is profile-scoped and persisted locally.
11. Search pagination defaults to bounded auto-pagination with configurable limits (`--limit`, `--max-pages`).
12. `--page-token` remains available for deterministic resume behavior.
13. Sorting semantics are explicit, stable, and deterministic with a required tie-breaker field.
14. Search filtering grammar is shared across meeting/transcript/recording discovery commands.
15. Transcript full-text search supports both upstream-backed mode (if available) and local-index fallback mode.
16. Local transcript index is opt-in and encrypted where platform support exists; plaintext fallback requires explicit override and warning.
17. Speaker-segment helpers operate on normalized transcript segment schema; if segment metadata is unavailable, command returns deterministic capability error.
18. Schema progression for Phase 2X:
   1. discovery/event additions: schema `1.2`
   2. host workflow additions: schema `1.3`
19. No breaking changes to existing Phase 1/1.1 fields without schema-major exception workflow.
20. Exit-code taxonomy reuses existing codes where possible; new domain codes require matrix and contract updates.
21. Event listener commands are non-daemon by default and support controlled long-running mode via explicit flags.
22. Long-running listener mode supports graceful shutdown and state checkpointing.
23. All commands emit request/event correlation IDs in `meta` and logs.
24. Host create/update commands support `--dry-run` contract validation when API supports preview; otherwise local validation-only dry run is enforced.
25. Recurring/template workflows are implemented as explicit subcommands, not hidden flags on base meeting commands.
26. Invitee operations support bulk input files with strict validation and partial-failure reporting.
27. Search query language supports case-insensitive matching by default, with optional `--case-sensitive`.
28. Timezone handling remains explicit and profile-aware; all persisted timestamps are UTC ISO 8601.
29. Feature gating:
   1. Event listener and host mutation commands are enabled by default after RC.
   2. Pre-RC release channel can disable host mutation with `WEBEX_PHASE2X_DISABLE_MUTATIONS=1` kill switch.
30. Security redaction applies to query strings, payload snapshots, webhook headers, and event-body logs.
31. Phase 2X introduces global `--non-interactive` for all command groups; any command requiring confirmation fails fast without prompt when set.
32. Event checkpoint commit happens only after successful handler completion (or DLQ handoff for terminal failures).
33. Default dedupe TTL window is 24 hours; configurable via settings and env.
34. Local transcript index freshness policy is explicit:
   1. on-demand incremental update during search
   2. forced rebuild via dedicated command
   3. stale-index warning when source cursor gap exceeds configured threshold.
35. Data retention defaults:
   1. event DLQ retention: 30 days
   2. idempotency cache retention: 7 days
   3. local transcript index retention: unlimited by default, opt-in pruning.
36. New local stores require explicit migration/version markers and backward-compatible lazy initialization.
37. Configuration precedence for all new settings is explicit: CLI flag > environment variable > profile config > global config > default.
38. `--non-interactive` applies uniformly to all commands; commands that would prompt must fail with deterministic validation error when confirmation flags are absent.
39. Event runtime semantics are explicit:
   1. per-event ack only after handler success or DLQ write
   2. nack triggers retry policy and bounded attempts
   3. shutdown drains in-flight workers up to configured timeout before exit.
40. New exit/error taxonomy entries for search/index/event/mutation paths are contract-governed and covered by compatibility tests.
41. Release rollback policy between schema `1.2` and `1.3` is mandatory and drill-tested before Host GA.
42. Event ingestion mechanism for Phase 2X is explicitly Webex Webhooks transport:
   1. `event ingress run` owns the local HTTP receiver and signature validation path
   2. ingress normalizes payloads and durably appends them to a profile-scoped local queue before any handler execution
   3. `event listen --source webex-webhook` consumes only from that durable local queue and never binds an HTTP port
   4. optional webhook auto-registration is supported via Webex webhook APIs
   5. polling-based event ingestion is out of scope for Phase 2X.
43. Filter DSL precedence is fixed: parentheses > `AND` > `OR`, with left-to-right evaluation inside same precedence group.
44. Filter string literals use single or double quotes with backslash escaping; `~` and `!~` are substring operators (not regex).
45. RRULE scope is intentionally constrained to supported fields (section 6.3); unsupported fields return deterministic validation errors.
46. Invitee bulk file format defaults to UTF-8 one-email-per-line with optional CSV mode (section 6.4).
47. SQLite-backed stores must use WAL mode, bounded busy timeout, and single-writer patterns for event queue/dedupe/index writes.
48. Global `--non-interactive` is canonical; command-local variants are deprecated aliases and must forward to global semantics.
49. Cross-platform shutdown behavior must be equivalent:
   1. Unix: SIGINT/SIGTERM
   2. Windows: CTRL_C_EVENT/KeyboardInterrupt console handling.
50. Local index encryption key lifecycle is profile-scoped and explicit (section 8.2), including loss/rebuild and rotation behavior.
51. `--dry-run` responses use explicit contract fields and never report mutation completion state (section 5.3).

---

## 4. Command Surface Specification

### 4.1 Discovery Commands

1. `webex meeting search --query <text> [--from <iso>] [--to <iso>] [--filter <expr>] [--sort <field:dir>] [--limit <n>] [--max-pages <n>] [--page-token <token>] [--case-sensitive] [--json]`
2. `webex transcript search --query <text> [--meeting-id <id>] [--speaker <name>] [--from <iso>] [--to <iso>] [--filter <expr>] [--sort <field:dir>] [--limit <n>] [--max-pages <n>] [--case-sensitive] [--json]`
3. `webex recording search --query <text> [--from <iso>] [--to <iso>] [--filter <expr>] [--sort <field:dir>] [--limit <n>] [--max-pages <n>] [--case-sensitive] [--json]`
4. `webex transcript segments <meeting_id> [--speaker <name>] [--contains <text>] [--from-offset <sec>] [--to-offset <sec>] [--case-sensitive] [--json]`
5. `webex transcript speakers <meeting_id> [--json]`
6. `webex transcript index rebuild [--from <iso>] [--to <iso>] [--json]`
7. `webex transcript index key rotate [--confirm|--yes] [--json]`

### 4.2 Shared Query and Pagination Options

1. `--filter <expr>` grammar (see section 6).
2. `--sort <field:asc|desc>` supports multiple comma-separated keys.
3. `--limit` hard-caps returned rows.
4. `--max-pages` bounds autopagination calls.
5. `--page-token` bypasses autopagination for deterministic single-page resume.
6. `--case-sensitive` switches string matching from default case-insensitive evaluation to case-sensitive evaluation.

### 4.3 Event Commands

1. `webex event listen [--source webex-webhook|file] [--source-path <path>] [--from <iso>] [--checkpoint <name>] [--max-events <n>] [--workers <n>] [--shutdown-timeout-sec <n>] [--payload-mode full|redacted|none] [--sink stdout|jsonl|file] [--sink-path <path>] [--json]`
2. `webex event ingress run [--bind-host <host>] [--bind-port <port>] [--public-base-url <https-url>] [--path /webhooks/webex] [--secret-env <env-var>] [--register] [--json]`
3. `webex event ingress status [--json]`
4. `webex event status [--checkpoint <name>] [--json]`
5. `webex event replay --from-dlq [--limit <n>] [--checkpoint <name>] [--force-replay] [--json]`
6. `webex event dlq list [--limit <n>] [--json]`
7. `webex event dlq purge [--older-than <iso>] --confirm [--json]`
8. `webex event checkpoint reset [--checkpoint <name>] --confirm [--json]`

### 4.4 Event transport contract

1. `webex-webhook` source:
   1. `event ingress run` receives HTTPS webhook POST payloads with signature headers.
   2. receiver validates signature using shared secret from `--secret-env` or profile config.
   3. payloads are normalized and appended to durable local queue store `events/<profile>/queue.db` before any handler fan-out.
   4. `event listen --source webex-webhook` consumes queued events by local queue sequence and checkpoint name.
2. Auto-registration behavior (`--register`):
   1. CLI calls Webex webhook API to create/update a webhook targeting `<public-base-url><path>`.
   2. if capability/permission is missing, command returns deterministic capability error with remediation.
3. Network/reachability requirements:
   1. inbound endpoint must be reachable from Webex delivery infrastructure.
   2. `--public-base-url` must be `https` and must terminate TLS at edge/tunnel/reverse-proxy.
   3. for local-only development, user may provide tunnel URL via `--public-base-url`.
4. `file` source:
   1. reads newline-delimited JSON events from `--source-path` for offline replay/testing.
   2. each input row is assigned a synthetic local sequence and processed through the same normalization/handler pipeline.
   3. signature validation is skipped by design for this mode.
### 4.5 Host Workflow Commands

1. `webex meeting create --title <text> --start <iso> --end <iso> [--timezone <iana>] [--agenda <text>] [--template-id <id>] [--invitees <email[,email...]>|--invitees-file <path>] [--invitees-file-format lines|csv] [--dry-run] [--idempotency-key <key>|--idempotency-auto] [--json]`
2. `webex meeting update <meeting_id> [--title <text>] [--start <iso>] [--end <iso>] [--agenda <text>] [--invitees-add <...>] [--invitees-remove <...>] [--dry-run] [--idempotency-key <key>|--idempotency-auto] [--json]`
3. `webex meeting cancel <meeting_id> [--reason <text>] [--notify true|false] [--confirm|--yes] [--idempotency-key <key>|--idempotency-auto] [--json]`
4. `webex meeting invitee list <meeting_id> [--json]`
5. `webex meeting invitee add <meeting_id> --invitees <email[,email...]>|--invitees-file <path> [--invitees-file-format lines|csv] [--idempotency-key <key>|--idempotency-auto] [--json]`
6. `webex meeting invitee remove <meeting_id> --invitees <email[,email...]>|--invitees-file <path> [--invitees-file-format lines|csv] [--idempotency-key <key>|--idempotency-auto] [--json]`
7. `webex meeting template list [--json]`
8. `webex meeting template apply --template-id <id> --start <iso> --end <iso> [--invitees ...] [--dry-run] [--idempotency-key <key>|--idempotency-auto] [--json]`
9. `webex meeting recurrence create --title <text> --rrule <rrule> --start <iso> --duration <min> [--invitees ...] [--dry-run] [--idempotency-key <key>|--idempotency-auto] [--json]`
10. `webex meeting recurrence update <series_id> [--rrule <rrule>] [--from-occurrence <iso>] [--dry-run] [--idempotency-key <key>|--idempotency-auto] [--json]`
11. `webex meeting recurrence cancel <series_id> [--from-occurrence <iso>] [--confirm|--yes] [--idempotency-key <key>|--idempotency-auto] [--json]`

### 4.6 Behavioral Semantics

1. Confirmation semantics:
   1. interactive mode: prompt unless `--confirm`/`--yes` supplied.
   2. non-interactive mode: require explicit `--confirm`/`--yes`, otherwise `VALIDATION_ERROR`.
2. Checkpoint semantics:
   1. for `webex-webhook`, checkpoint tracks last committed local queue sequence per checkpoint name.
   2. for `file`, checkpoint tracks `source_path` plus last committed record number.
   3. event marked complete only after handler success or DLQ write.
   4. checkpoint update is atomic and monotonic.
   5. checkpoint commit occurs after ack and before next dispatch from the same source/checkpoint pair.
3. Retry/ack semantics:
   1. transient failures emit `nack` and follow bounded retry policy.
   2. terminal failures are written to DLQ with error classification and then acknowledged.
   3. retry classification uses deterministic error taxonomy (see section 5.4).
4. Replay semantics:
   1. DLQ replay preserves original `event_id` and increments `delivery_attempt`.
   2. replayed events still pass dedupe rules unless `--force-replay` is specified.
5. Shutdown semantics:
   1. SIGINT/SIGTERM (or Windows console interrupt) stop new ingestion immediately.
   2. in-flight workers drain until `--shutdown-timeout-sec` then abort with partial-progress warning.
   3. final checkpoint write is attempted exactly once during shutdown drain.
6. Index semantics:
   1. transcript search without upstream capability and without local index returns deterministic capability error with remediation command.
   2. `transcript index rebuild` is profile-scoped and interrupt-safe.
   3. search auto-triggers incremental index refresh when stale window threshold is exceeded.
   4. stale window threshold is configurable and defaults to 6 hours.
7. Source-specific semantics:
   1. signature validation is required for `webex-webhook` source and not applicable to `file` source.
   2. ingress endpoint bind/start failures are fatal and produce deterministic startup errors.
8. Idempotency semantics:
   1. non-interactive mutation commands without key fail fast unless explicitly opted into generated-key mode.
   2. key format is `^[A-Za-z0-9._-]{1,128}$`.
   3. generated keys are echoed in response payload and logs for explicit reuse.

### 4.7 Capability negotiation behavior

1. Commands requiring upstream optional features must execute capability probe before main call:
   1. transcript upstream search
   2. templates list/apply
   3. recurrence mutation endpoints
   4. invitee mutation endpoints
   5. webhook registration endpoints.
2. On missing capability:
   1. return deterministic feature-specific capability code (`SEARCH_CAPABILITY_UNAVAILABLE`, `TEMPLATE_CAPABILITY_UNAVAILABLE`, `RECURRENCE_CAPABILITY_UNAVAILABLE`, `INVITEE_MUTATION_UNAVAILABLE`, `EVENT_INGRESS_CAPABILITY_UNAVAILABLE`)
   2. include remediation hint and fallback command where applicable.
3. Capability probe results are cached per profile for 15 minutes and invalidated on auth/profile changes.

---

## 5. Output Contract Extensions

### 5.1 Envelope Stability

1. Required top-level keys remain immutable:
   1. `ok`
   2. `command`
   3. `data`
   4. `warnings`
   5. `error`
   6. `meta`

### 5.2 `meta` requirements

1. `request_id`
2. `timestamp`
3. `cli_version`
4. `schema_version`
5. `duration_ms`
6. `profile`
7. `command_mode` (`read`, `listen`, `mutation`)
8. Compatibility semantics:
   1. all pre-existing read commands emit `command_mode=read`
   2. listener and ingress commands emit `command_mode=listen`
   3. host mutation commands emit `command_mode=mutation`
   4. existing `data.profile` fields on auth/profile commands remain allowed and are not contract conflicts.

### 5.3 New data contracts (additive)

1. Search result item includes:
   1. `resource_type`
   2. `resource_id`
   3. `title`
   4. `snippet`
   5. `score`
   6. `sort_key`
2. Transcript segment item includes:
   1. `segment_id`
   2. `speaker`
   3. `start_offset_ms`
   4. `end_offset_ms`
   5. `text`
3. Event item includes:
   1. `event_id`
   2. `event_type`
   3. `occurred_at`
   4. `resource_id`
   5. `delivery_attempt`
   6. `payload`
4. Mutation response includes:
   1. `operation_id`
   2. `idempotency_key`
   3. `state` (`accepted|completed|no_op|dry_run_validated`)
   4. `dry_run` (bool)
   5. `dry_run_mode` (`upstream_preview|local_validation|none`)
   6. `validation` (field-level validation report for dry-run paths)
   7. `warnings`

### 5.4 Error and exit taxonomy extensions

1. New deterministic error `code` values:
   1. `SEARCH_CAPABILITY_UNAVAILABLE`
   2. `TEMPLATE_CAPABILITY_UNAVAILABLE`
   3. `RECURRENCE_CAPABILITY_UNAVAILABLE`
   4. `INVITEE_MUTATION_UNAVAILABLE`
   5. `EVENT_INGRESS_CAPABILITY_UNAVAILABLE`
   6. `INDEX_NOT_READY`
   7. `INDEX_STALE`
   8. `EVENT_RETRY_EXHAUSTED`
   9. `EVENT_SIGNATURE_INVALID`
   10. `MUTATION_CONFLICT`
   11. `CONFIRMATION_REQUIRED_NON_INTERACTIVE`
2. DomainCode additions:
   1. `CAPABILITY_ERROR`
   2. `STATE_ERROR`
   3. `CONFLICT_ERROR`
3. Error-to-domain-to-exit mapping:
   1. `SEARCH_CAPABILITY_UNAVAILABLE` -> `CAPABILITY_ERROR` -> exit `5` -> retryable `False`
   2. `TEMPLATE_CAPABILITY_UNAVAILABLE` -> `CAPABILITY_ERROR` -> exit `5` -> retryable `False`
   3. `RECURRENCE_CAPABILITY_UNAVAILABLE` -> `CAPABILITY_ERROR` -> exit `5` -> retryable `False`
   4. `INVITEE_MUTATION_UNAVAILABLE` -> `CAPABILITY_ERROR` -> exit `5` -> retryable `False`
   5. `EVENT_INGRESS_CAPABILITY_UNAVAILABLE` -> `CAPABILITY_ERROR` -> exit `5` -> retryable `False`
   6. `INDEX_NOT_READY` -> `STATE_ERROR` -> exit `2` -> retryable `False`
   7. `INDEX_STALE` -> `STATE_ERROR` -> exit `2` -> retryable `True`
   8. `EVENT_RETRY_EXHAUSTED` -> `UPSTREAM_UNAVAILABLE` -> exit `6` -> retryable `False`
   9. `EVENT_SIGNATURE_INVALID` -> `VALIDATION_ERROR` -> exit `2` -> retryable `False`
   10. `MUTATION_CONFLICT` -> `CONFLICT_ERROR` -> exit `8` -> retryable `False`
   11. `CONFIRMATION_REQUIRED_NON_INTERACTIVE` -> `VALIDATION_ERROR` -> exit `2` -> retryable `False`
4. Error object contract requirements:
   1. `error.code`
   2. `error.message`
   3. `error.retryable`
   4. `error.details` (typed map with remediation hints where applicable)
5. Any new code additions require:
   1. exit-code matrix update
   2. contract fixture update
   3. compatibility gate test in CI.

---

## 6. Filter and Sort Grammar

### 6.1 Filter DSL

1. Expression syntax: `<field><op><value>` joined by `AND`/`OR` with parentheses.
2. Operator precedence:
   1. parentheses
   2. `AND`
   3. `OR`
3. String literals:
   1. single-quoted and double-quoted forms are both valid
   2. backslash escapes quotes and backslash
   3. unquoted tokens are allowed only for simple alnum/underscore values.
4. Supported operators:
   1. `=`
   2. `!=`
   3. `~` (contains)
   4. `!~`
   5. `>`
   6. `>=`
   7. `<`
   8. `<=`
   9. `IN (...)`
5. `~` and `!~` are substring operators (not regex).
6. Field names are case-insensitive; canonical lower-case names are used internally.
7. Type-aware parsing for bool/int/time/string.
8. String comparisons (`=`, `!=`, `~`, `!~`, and string members of `IN`) are case-insensitive by default; `--case-sensitive` switches evaluation to case-sensitive for the command invocation.
9. Unknown fields or incompatible operators return `VALIDATION_ERROR` with parser location details.
10. Shell safety guidance:
   1. users should quote full expression: `--filter "title~'QBR' AND start>='2026-01-01T00:00:00Z'"`.
   2. parser errors must include line/column offsets and token context.

### 6.2 Sort

1. Sort specification: `field:asc|desc` (default asc if omitted).
2. Multiple sort keys allowed, comma-separated.
3. Stable tie-breaker auto-appended per resource type:
   1. meetings: `meeting_id`
   2. transcripts: `transcript_id`
   3. recordings: `recording_id`

### 6.3 RRULE support scope

1. Supported RRULE keys:
   1. `FREQ`
   2. `INTERVAL`
   3. `COUNT`
   4. `UNTIL`
   5. `BYDAY`
   6. `BYMONTHDAY`
   7. `BYMONTH`
   8. `WKST`
2. Unsupported keys (for Phase 2X) return deterministic validation error:
   1. `BYSETPOS`
   2. `BYYEARDAY`
   3. `BYWEEKNO`
3. Validation approach:
   1. parse and validate using a standard RRULE parser library
   2. enforce timezone normalization at command boundary
   3. reject values that parse but are unsupported by upstream capability probe.

### 6.4 Invitee bulk file format

1. Default file mode (`--invitees-file`):
   1. UTF-8 text
   2. one email per line
   3. optional comment lines starting with `#`
2. Optional CSV mode (`--invitees-file-format csv`):
   1. UTF-8 CSV
   2. required header `email`
3. Validation rules:
   1. max entries per invocation: 5000
   2. duplicate emails in input are collapsed and emitted in warnings
   3. invalid rows are reported with row numbers in partial-failure output.

---

## 7. Architecture and Data Design

### 7.1 New modules

1. `webex_cli/search/`
   1. query parser
   2. filter evaluator
   3. rankers and snippet builder
2. `webex_cli/events/`
   1. listener runtime
   2. queue store
   3. checkpoint store
   4. dedupe store
   5. DLQ store
3. `webex_cli/host/`
   1. payload validators
   2. idempotency helpers
   3. recurrence/template adapters
4. `webex_cli/contracts/`
   1. schema fixture loader for `1.2` and `1.3`

### 7.2 Storage additions (profile-scoped)

1. `events/<profile>/checkpoints.json`
2. `events/<profile>/queue.db` (sqlite durable ingress queue)
3. `events/<profile>/dedupe.db` (sqlite)
4. `events/<profile>/dlq.jsonl`
5. `search/<profile>/transcript-index.db` (opt-in local index)
6. `mutations/<profile>/idempotency-cache.json`

### 7.3 Concurrency model

1. Discovery commands remain request/response with bounded pagination loops.
2. Event listener uses bounded worker pool for event handlers and drains from queue/file adapters with deterministic sequence ordering per checkpoint.
3. Queue, dedupe, and checkpoint writes use atomic transaction/file semantics.
4. Mutation operations serialize per meeting-series when required to avoid conflicting updates.

### 7.4 Local store migration and retention model

1. All new local stores include version marker files:
   1. `events/<profile>/meta.json`
   2. `search/<profile>/meta.json`
   3. `mutations/<profile>/meta.json`
2. Lazy initialization rules:
   1. stores created on first command that needs them
   2. creation is profile-scoped and idempotent
3. Migration rules:
   1. forward migrations are automatic and transactional when possible
   2. failed migrations leave prior state intact and return deterministic migration error
4. Retention and cleanup rules:
   1. DLQ cleanup uses `event dlq purge` and retention defaults from section 3
   2. idempotency cache cleanup runs on mutation command startup with bounded cleanup work
   3. transcript index pruning is optional and controlled by config
5. Compatibility rules:
   1. schema `1.2` binaries can read pre-host stores without requiring host store initialization
   2. schema `1.3` binaries must tolerate missing legacy marker fields and self-heal.

### 7.5 SQLite concurrency model

1. SQLite stores (`queue.db`, `dedupe.db`, `transcript-index.db`) run in WAL mode.
2. Busy timeout is explicitly configured (default 5000ms) and configurable.
3. Event runtime uses single-writer queue semantics for queue and dedupe mutations; workers do read-mostly operations.
4. Checkpoint writes are outside SQLite and remain atomic file writes.
5. Storage location safety:
   1. warn when config path is on network filesystem
   2. fallback to conservative single-process mode when reliable locking is unavailable.

---

## 8. Security and Safety Model

1. Sensitive payload fields are redacted before logs and persisted diagnostics.
2. Event payload persistence supports `--payload-mode full|redacted|none` (default `redacted`).
3. Webhook signatures are validated when provider signature headers are present.
4. Mutation commands include explicit guardrails:
   1. `--dry-run`
   2. `--confirm`/`--yes` for destructive commands
   3. idempotency key tracking
5. Local index encryption policy:
   1. use OS secure storage for index key material where possible
   2. fallback to passphrase-derived key only with explicit user opt-in
6. Non-interactive policy:
   1. commands fail fast if required confirmations are missing
   2. no prompt emission when `--non-interactive` is set

### 8.1 Configuration and environment surface

1. New profile/global settings keys:
   1. `events.workers`
   2. `events.shutdown_timeout_sec`
   3. `events.dedupe_ttl_hours`
   4. `events.dlq_retention_days`
   5. `events.ingress.bind_host`
   6. `events.ingress.bind_port`
   7. `events.ingress.public_base_url`
   8. `events.ingress.path`
   9. `events.ingress.secret_env`
   10. `search.local_index_enabled`
   11. `search.local_index_stale_hours`
   12. `search.local_index_prune_days`
   13. `mutations.idempotency_retention_days`
2. New environment variables:
   1. `WEBEX_EVENTS_WORKERS`
   2. `WEBEX_EVENTS_SHUTDOWN_TIMEOUT_SEC`
   3. `WEBEX_EVENTS_DEDUPE_TTL_HOURS`
   4. `WEBEX_EVENTS_DLQ_RETENTION_DAYS`
   5. `WEBEX_EVENTS_INGRESS_BIND_HOST`
   6. `WEBEX_EVENTS_INGRESS_BIND_PORT`
   7. `WEBEX_EVENTS_INGRESS_PUBLIC_BASE_URL`
   8. `WEBEX_EVENTS_INGRESS_PATH`
   9. `WEBEX_EVENTS_INGRESS_SECRET_ENV`
   10. `WEBEX_SEARCH_LOCAL_INDEX_ENABLED`
   11. `WEBEX_SEARCH_LOCAL_INDEX_STALE_HOURS`
   12. `WEBEX_SEARCH_LOCAL_INDEX_PRUNE_DAYS`
   13. `WEBEX_MUTATIONS_IDEMPOTENCY_RETENTION_DAYS`
   14. `WEBEX_PHASE2X_DISABLE_MUTATIONS`
3. Resolution order (global):
   1. CLI flag
   2. environment variable
   3. active profile config
   4. global config
   5. default.

### 8.2 Local index key lifecycle

1. Key material:
   1. one data-encryption key (DEK) per profile
   2. DEK protected by OS secure storage when available
   3. fallback passphrase mode is opt-in and explicit.
2. Cryptography baseline:
   1. AES-256-GCM for index page/chunk encryption
   2. unique nonce per encrypted record/page
3. Lifecycle operations:
   1. key creation on first encrypted index write
   2. key rotation via `webex transcript index key rotate --profile <name>`
   3. key loss recovery path is deterministic: delete encrypted index and rebuild.
4. Profile isolation:
   1. no key sharing across profiles
   2. cross-profile reads are forbidden even when path-level access exists.

---

## 9. Performance SLOs

1. Meeting/transcript search over 10k items returns first page in <2.5s on reference laptop.
2. Event listener sustains 50 events/sec with <1% DLQ rate under nominal conditions.
3. Mutation command median latency <1.5s excluding upstream waits.
4. Memory ceiling:
   1. search command <300 MB
   2. listener worker <500 MB
5. No unbounded in-memory buffers for downloads/events.

---

## 10. Implementation Task Board

| Status | ID | Sprint | Lane | Owner | Task | Depends On | Estimate | Definition of Done |
|---|---|---:|---|---|---|---|---:|---|
| `pending` | P2X-GOV-01 | 0 | Governance | `@owner-platform` | Publish Phase 2X contract addendum with schema and compatibility policy (`1.2` + `1.3`) | None | 0.5d | Addendum approved and linked in roadmap |
| `pending` | P2X-GOV-02 | 0 | Governance | `@owner-platform` | Define release gates: Discovery GA and Host GA criteria | P2X-GOV-01 | 0.5d | RC/GA gates documented with explicit tests |
| `pending` | P2X-GOV-03 | 0 | Governance | `@owner-security` | Define mutation safety checklist and destructive command policy | P2X-GOV-01 | 0.5d | Safety checklist published and test-linked |
| `pending` | P2X-PRE-01 | 0 | Preflight | `@owner-qa` | Validate carryover bug guardrail suite (`_normalize_page`, streaming downloads, settings concurrency, unexpected-error diagnostics policy) | None | 1.0d | Preflight suite green and linked in gate artifacts |
| `pending` | P2X-PRE-02 | 0 | Preflight | `@owner-cli` | Unify global `--non-interactive` with auth-local legacy flag behavior | P2X-GOV-01 | 0.75d | One canonical behavior with alias/deprecation tests |
| `pending` | P2X-CFG-01 | 0 | Governance | `@owner-platform` | Define settings/env schema and precedence rules for all Phase 2X knobs | P2X-GOV-01 | 0.5d | Config keys and env vars documented with precedence tests planned |
| `pending` | P2X-CAP-01 | 0 | Capability | `@owner-platform` | Produce upstream capability matrix (events transport, templates, recurrence, invitees, transcript search) | P2X-GOV-01 | 1.0d | Matrix published with per-feature fallback policy |
| `pending` | P2X-OBS-01 | 0 | Observability | `@owner-platform` | Extend command meta for `profile` and `command_mode` before schema 1.2 features | P2X-GOV-01 | 0.5d | Envelope fixtures updated and back-compat verified |
| `pending` | P2X-CAP-02 | 1 | Capability | `@owner-platform` | Implement shared capability probe framework and deterministic capability errors | P2X-CAP-01 | 1.0d | Capability checks reusable across lanes |
| `pending` | P2X-QRY-01 | 1 | Discovery | `@owner-search` | Implement shared query parser for filter DSL (precedence, quoting, escapes, typed literals) | P2X-GOV-01, P2X-PRE-01 | 3.5d | Parser supports grammar and typed AST with location diagnostics |
| `pending` | P2X-QRY-02 | 1 | Discovery | `@owner-search` | Implement shared sorter and tie-breaker policy | P2X-QRY-01 | 1.0d | Deterministic sorted outputs across resources |
| `pending` | P2X-QRY-03 | 1 | Discovery | `@owner-cli` | Implement pagination ergonomics (`--limit`, `--max-pages`, resume token behavior) | P2X-QRY-01 | 1.0d | Bounded autopagination with deterministic warnings |
| `pending` | P2X-QRY-04 | 1 | Discovery | `@owner-qa` | Add unit tests for parser/sort/pagination edge cases | P2X-QRY-03 | 1.5d | Coverage includes parser location diagnostics |
| `pending` | P2X-CFG-02 | 1 | Discovery | `@owner-cli` | Implement config/env resolution for search/event/host options | P2X-CFG-01 | 1.0d | Runtime resolution follows documented precedence with tests |
| `pending` | P2X-SRCH-01 | 2 | Discovery | `@owner-search` | Add `meeting search` command + normalization/ranking | P2X-QRY-03 | 1.5d | Contract fixture and CLI tests pass |
| `pending` | P2X-SRCH-02 | 2 | Discovery | `@owner-search` | Add `recording search` command + normalization/ranking | P2X-QRY-03 | 1.5d | Contract fixture and CLI tests pass |
| `pending` | P2X-SRCH-03 | 2 | Discovery | `@owner-search` | Add transcript search upstream adapter capability detection | P2X-QRY-03, P2X-CAP-02 | 1.0d | Capability errors are deterministic and actionable |
| `pending` | P2X-SRCH-04 | 2 | Discovery | `@owner-search` | Implement local transcript index mode (opt-in) | P2X-SRCH-03 | 2.0d | Index build/search commands working with profile isolation |
| `pending` | P2X-SRCH-05 | 2 | Discovery | `@owner-security` | Add local index encryption and redaction policy | P2X-SRCH-04 | 1.0d | Encryption and fallback controls verified |
| `pending` | P2X-SRCH-07 | 2 | Discovery | `@owner-search` | Implement stale-index detection and incremental refresh behavior | P2X-SRCH-04, P2X-CFG-02 | 1.0d | Freshness thresholds and warning behaviors verified |
| `pending` | P2X-SRCH-08 | 2 | Discovery | `@owner-security` | Implement local index key lifecycle (create/rotate/loss-rebuild) | P2X-SRCH-05 | 1.5d | Key lifecycle commands and recovery path verified |
| `pending` | P2X-SRCH-06 | 2 | Discovery | `@owner-qa` | Integration tests for search precision and pagination bounds | P2X-SRCH-05, P2X-SRCH-07, P2X-SRCH-08 | 1.5d | Precision/recall smoke thresholds enforced |
| `pending` | P2X-SPK-01 | 3 | Discovery | `@owner-transcript` | Add `transcript segments` command with offset and speaker filters | P2X-SRCH-03 | 1.5d | Segment contract fixture added |
| `pending` | P2X-SPK-02 | 3 | Discovery | `@owner-transcript` | Add `transcript speakers` command | P2X-SPK-01 | 0.5d | Deterministic speaker aggregate outputs |
| `pending` | P2X-SPK-03 | 3 | Discovery | `@owner-qa` | Add tests for missing-segment capability errors and filter behavior | P2X-SPK-02 | 0.75d | Edge-case behavior covered |
| `pending` | P2X-EVT-08 | 4 | Events | `@owner-events-ingress` | Build webhook ingress runtime (HTTP receiver, auth secret loading, durable queue append) | P2X-CAP-02, P2X-CFG-02 | 2.0d | Ingress receives/normalizes payloads and stores `queue.db` entries |
| `pending` | P2X-EVT-09 | 4 | Events | `@owner-events-ingress` | Implement webhook auto-registration/update flows | P2X-EVT-08, P2X-CAP-02 | 1.5d | Register/update status commands pass with deterministic fallback errors |
| `pending` | P2X-EVT-10 | 4 | Events | `@owner-events-ingress` | Implement file-source ingestion adapter for offline replay/testing | P2X-EVT-08 | 0.75d | `--source file` supports deterministic replay input |
| `pending` | P2X-EVT-01 | 4 | Events | `@owner-events-core` | Build checkpoint store (profile-scoped) | P2X-GOV-01 | 1.0d | Atomic checkpoint persistence |
| `pending` | P2X-EVT-02 | 4 | Events | `@owner-events-core` | Build dedupe store with TTL window | P2X-EVT-01 | 1.0d | Duplicate suppression validated |
| `pending` | P2X-STR-01 | 4 | Events | `@owner-platform` | Implement local store version markers and lazy initialization | P2X-GOV-01 | 1.0d | `events/search/mutations` stores initialize and migrate safely |
| `pending` | P2X-STR-03 | 4 | Events | `@owner-platform` | Implement sqlite WAL, busy-timeout, and single-writer queue controls for `queue.db`/`dedupe.db`/`transcript-index.db` | P2X-EVT-02, P2X-STR-01 | 1.0d | Concurrency policy validated under multi-worker load |
| `pending` | P2X-EVT-11 | 4 | Events | `@owner-events-ingress` | Implement cross-platform shutdown handlers (Unix + Windows console) | P2X-EVT-08 | 0.75d | Equivalent graceful shutdown behavior across platforms |
| `pending` | P2X-EVT-03 | 5 | Events | `@owner-events-core` | Build DLQ store and replay primitives | P2X-EVT-02 | 1.5d | DLQ list/replay/purge commands pass tests |
| `pending` | P2X-EVT-04 | 5 | Events | `@owner-events-core` | Add `event listen` runtime with bounded worker pool for queue-backed and file-backed sources | P2X-EVT-03, P2X-EVT-08 | 2.0d | Listener handles graceful shutdown and checkpoints across both source modes |
| `pending` | P2X-EVT-07 | 5 | Events | `@owner-events-core` | Implement ack/nack state machine and checkpoint-commit ordering | P2X-EVT-04 | 1.0d | Commit-after-ack semantics verified under interruption |
| `pending` | P2X-EVT-05 | 5 | Events | `@owner-security` | Add event payload redaction/signature validation | P2X-EVT-08 | 1.0d | Signature failure and redaction tests pass |
| `pending` | P2X-EVT-06 | 5 | Events | `@owner-qa` | Event reliability tests (retry/backoff/DLQ paths) | P2X-EVT-05, P2X-EVT-07, P2X-EVT-11 | 1.5d | Reliability scenarios pass deterministically |
| `pending` | P2X-STR-02 | 5 | Events | `@owner-platform` | Add migration rollback safety + retention cleanup routines | P2X-STR-01, P2X-CFG-02 | 1.0d | Failed migration rollback and cleanup paths covered by tests |
| `pending` | P2X-CAP-03 | 5 | Capability | `@owner-platform` | Implement host capability probes (templates/recurrence/invitees mutation support) | P2X-CAP-02 | 1.0d | Host commands fail deterministically when capability missing |
| `pending` | P2X-HOST-01 | 6 | Host | `@owner-host-core` | Implement host adapter for create/update/cancel | P2X-GOV-03, P2X-CAP-03 | 2.0d | Mutation adapter with explicit payload validators |
| `pending` | P2X-HOST-10 | 6 | Host | `@owner-host-core` | Implement idempotency key policy (required modes, format constraints, reporting) | P2X-HOST-01 | 1.0d | Key behavior documented and tested for retries |
| `pending` | P2X-HOST-09 | 6 | Host | `@owner-host-core` | Implement explicit dry-run response contract and states | P2X-HOST-01 | 1.0d | `dry_run` contract fields present in all mutation dry-run responses |
| `pending` | P2X-HOST-02 | 6 | Host | `@owner-host-core` | Add `meeting create` with dry-run + idempotency key support | P2X-HOST-09, P2X-HOST-10 | 1.5d | Create contract fixtures and tests pass |
| `pending` | P2X-HOST-03 | 6 | Host | `@owner-host-core` | Add `meeting update` with partial field patch semantics | P2X-HOST-09, P2X-HOST-10 | 1.5d | Update safety and idempotency tests pass |
| `pending` | P2X-HOST-04 | 6 | Host | `@owner-host-core` | Add `meeting cancel` with confirm policy | P2X-HOST-01 | 1.0d | Destructive confirmation behavior enforced |
| `pending` | P2X-HOST-11 | 7 | Host | `@owner-host-collab` | Implement invitee bulk file parser modes (line/csv) + validation limits | P2X-HOST-03 | 1.0d | File parsing is deterministic with row-level diagnostics |
| `pending` | P2X-HOST-05 | 7 | Host | `@owner-host-collab` | Add invitee subcommands (list/add/remove, bulk file support) | P2X-HOST-11 | 1.5d | Partial-failure reporting contract implemented |
| `pending` | P2X-HOST-06 | 7 | Host | `@owner-host-sched` | Add template list/apply commands with dry-run + idempotency support | P2X-HOST-02, P2X-CAP-03 | 1.0d | Template application flows and mutation safeguards are covered |
| `pending` | P2X-HOST-12 | 7 | Host | `@owner-host-sched` | Implement constrained RRULE validation/profile-aware normalization | P2X-HOST-01, P2X-CAP-03 | 1.5d | Supported/unsupported RRULE behavior deterministic |
| `pending` | P2X-HOST-07 | 7 | Host | `@owner-host-sched` | Add recurrence create/update/cancel commands with dry-run/confirm/idempotency support | P2X-HOST-12, P2X-HOST-06 | 1.5d | RRULE scope, series operations, and mutation safeguards are tested |
| `pending` | P2X-HOST-08 | 7 | Host | `@owner-qa` | Host workflow integration tests and conflict scenarios | P2X-HOST-05, P2X-HOST-07 | 2.0d | Conflict/idempotency regressions covered |
| `pending` | P2X-OBS-02 | 8 | Observability | `@owner-platform` | Add event correlation propagation across listener pipeline | P2X-EVT-04 | 1.0d | End-to-end traceability validated |
| `pending` | P2X-OBS-03 | 8 | Observability | `@owner-platform` | Add performance timing spans for search and host mutations | P2X-SRCH-06, P2X-HOST-08 | 1.0d | Timings emitted consistently |
| `pending` | P2X-CON-01 | 8 | Contracts | `@owner-platform` | Create `schema 1.2` fixtures for discovery + events | P2X-OBS-01, P2X-SRCH-06, P2X-EVT-06 | 1.5d | Fixture suite green |
| `pending` | P2X-CON-02 | 8 | Contracts | `@owner-platform` | Create `schema 1.3` fixtures for host workflows | P2X-HOST-08 | 1.5d | Fixture suite green |
| `pending` | P2X-CON-03 | 8 | Contracts | `@owner-platform` | Exit-code matrix extension and compatibility tests | P2X-CON-01 | 1.0d | Matrix gate enforced |
| `pending` | P2X-CON-05 | 8 | Contracts | `@owner-platform` | Add DomainCode entries and runtime mappings for new capability/state/conflict families | P2X-CON-03 | 1.0d | `errors/codes.py` and `errors/mapping.py` remain exhaustive and tested |
| `pending` | P2X-CON-04 | 8 | Contracts | `@owner-platform` | Add deterministic error-code fixtures for search/index/event/mutation | P2X-CON-03, P2X-CON-05 | 1.0d | New taxonomy is fixture-locked and CI-gated |
| `pending` | P2X-CI-01 | 8 | Contracts | `@owner-platform` | CI gate policy for 1.2/1.3 phased blocking | P2X-CON-03, P2X-CON-04, P2X-GOV-02 | 1.0d | Warn/block rules active by branch/tag |
| `pending` | P2X-DOC-01 | 8 | Docs | `@owner-docs` | Update README and command reference for discovery and events | P2X-CON-01 | 1.0d | Docs align with CLI help and fixtures |
| `pending` | P2X-DOC-02 | 9 | Docs | `@owner-docs` | Publish host workflow operator guide and safety playbooks | P2X-CON-02, P2X-GOV-03 | 1.0d | Operational guide complete |
| `pending` | P2X-REL-01 | 9 | Release | `@owner-platform` | Execute Discovery+Events go/no-go checklist (1.2 cut) | P2X-CI-01, P2X-DOC-01 | 0.5d | Discovery/event release approved |
| `pending` | P2X-REL-02 | 10 | Release | `@owner-platform` | Execute Host workflow go/no-go checklist (1.3 cut) | P2X-HOST-08, P2X-DOC-02, P2X-CI-01 | 0.5d | Host release approved |
| `pending` | P2X-REL-03 | 10 | Release | `@owner-platform` | Run schema rollback drill (1.3 -> 1.2 compatibility fallback) | P2X-REL-01, P2X-HOST-08, P2X-CON-04 | 0.5d | Rollback procedure validated and documented |

### 10.1 Capacity and parallelization check

1. Sprint numbering is a milestone sequence, not a single-owner serial backlog.
2. Events lane is split across `@owner-events-ingress`, `@owner-events-core`, `@owner-platform`, `@owner-security`, and `@owner-qa`.
3. Host lane is split across `@owner-host-core`, `@owner-host-collab`, `@owner-host-sched`, and `@owner-qa`.
4. Any sprint with >8 owner-days for one owner requires split or resequencing before kickoff.
5. Critical-path guard:
   1. no single-owner chain in one sprint should exceed 5.0d without explicit staffing exception.

---

## 11. Critical Path

1. Governance locks (`P2X-GOV-*`).
2. Carryover preflight and capability baseline (`P2X-PRE-*`, `P2X-CAP-*`).
3. Config/env + early meta contract foundation (`P2X-CFG-*`, `P2X-OBS-01`).
4. Shared query + pagination substrate (`P2X-QRY-*`).
5. Discovery commands and transcript indexing (`P2X-SRCH-*`, `P2X-SPK-*`).
6. Event ingestion transport + local store foundation (`P2X-EVT-*`, `P2X-STR-*`).
7. Host mutation stack (split across core and advanced lanes, `P2X-HOST-*`).
8. Late observability and contracts (`P2X-OBS-02/03`, `P2X-CON-*`, `P2X-CI-01`).
9. Documentation and staged releases (`P2X-DOC-*`, `P2X-REL-*`).

---

## 12. Detailed Test Matrix

### 12.1 Unit Tests

1. Filter parser success/failure with source location reporting.
2. Sort parser and stable tie-breakers.
3. Pagination guards (`max-pages`, `limit`, cycle detection, no-progress).
4. Search ranker scoring determinism.
5. Snippet extraction and redaction behavior.
6. Transcript segment normalization with missing fields.
7. Event dedupe TTL behavior.
8. Event checkpoint atomicity under interruption.
9. DLQ write/read/cleanup behavior.
10. Mutation payload validators for each command.
11. Idempotency key generation and replay behavior.
12. Confirmation-policy enforcement in non-interactive mode.
13. Recurrence RRULE validation and timezone normalization.
14. Contract fixture loaders for 1.2 and 1.3.
15. Exit code mapping for new domain conditions.
16. Config/env precedence resolution and fallback defaults.
17. Local store migration failure rollback behavior.
18. Global/local `--non-interactive` alias behavior parity.
19. RRULE supported/unsupported key validation.
20. Invitee file parser modes and row-level diagnostics.
21. Error-code to DomainCode to exit-code/retryable mapping integrity.
22. Case-sensitive versus case-insensitive string evaluation.

### 12.2 Integration Tests (mock upstream)

1. Meeting search precision for mixed title/topic payloads.
2. Transcript search upstream mode and fallback index mode.
3. Recording search with filter/sort combinations.
4. Segment command behavior with and without speaker metadata.
5. Event listener retry, DLQ, and replay flows.
6. Event dedupe under duplicate delivery storms.
7. Host create/update/cancel success and policy failures.
8. Invitee bulk add/remove partial-failure reporting.
9. Template apply and recurrence lifecycle flows.
10. Idempotent replays produce no duplicate remote mutations.
11. Mutation conflicts map to deterministic CLI errors.
12. `--dry-run` behavior for supported and unsupported preview APIs.
13. Listener shutdown drain behavior with in-flight workers and bounded timeout.
14. Incremental index refresh when stale threshold exceeded.
15. Webhook auto-registration success/fallback paths.
16. Host capability probe gating for templates/recurrence/invitees.
17. Dry-run response contract shape for preview vs local-validation modes.
18. Event ingress start-up validation for `https` public URL requirements.
19. Event replay with and without `--force-replay` respects dedupe policy.

### 12.3 CLI E2E Smoke

1. Search commands in human and JSON modes.
2. Pagination and resume token workflows.
3. Event listener start/stop/checkpoint/resume.
4. DLQ inspect and replay flows.
5. Host mutation commands with explicit confirmations.
6. Recurrence and template workflows on representative fixtures.
7. Cross-profile isolation for search index and event stores.
8. Global `--profile` behavior across all new commands.
9. Global `--non-interactive` behavior across destructive command paths.
10. Event ingress run/listen behavior on Windows PowerShell and Unix shells.
11. Non-interactive alias behavior parity for `auth login`.

### 12.4 Performance and Soak

1. Search latency benchmark across 1k/10k datasets.
2. Event listener soak test (60 min sustained load).
3. Mutation burst tests with idempotency guarantees.
4. Memory ceiling tests for stream processing and indexing.
5. Configured worker + sqlite lock settings under load profiles.

### 12.5 Security Tests

1. Redaction coverage for query strings, event payloads, and mutation payload logs.
2. Local index encryption and fallback policy behavior.
3. Signature validation failure handling.
4. Confirmation bypass prevention in non-interactive mode.
5. Profile isolation for event/checkpoint/index stores.
6. Local store migration tamper/error handling.
7. Index key rotation and lost-key rebuild safety.
8. Webhook signature + secret loading behavior for ingress source.

### 12.6 Contract and CI Gate Tests

1. Envelope compatibility for schema 1.2 and 1.3 fixtures.
2. Exit-code matrix immutability.
3. Branch/tag-aware gate behavior (warn/block).
4. Release checklists as required CI artifacts.
5. Error taxonomy fixture stability across schema 1.2 and 1.3.
6. Meta field compatibility (`profile`, `command_mode`) for all command families.

---

## 13. Commit Strategy

Aligned with `docs/2026-03-03-implementation-commit-strategy.md`.

1. One task or tightly coupled task-pair per commit.
2. Prefixes:
   1. `feat:` behavior
   2. `fix:` bug/contract corrections
   3. `test:` test-only
   4. `docs:` documentation-only
   5. `ci:` pipeline and gate controls
3. No mixed-scope commits across lanes.
4. Each behavior commit includes tests in same or immediate next commit.
5. No amend/force-push without explicit approval.

### 13.1 Planned commit sequence (high-level)

1. Governance + preflight + early meta contract (`P2X-GOV-*`, `P2X-PRE-*`, `P2X-OBS-01`).
2. Capability baseline + config/env foundation (`P2X-CAP-*`, `P2X-CFG-*`).
3. Query/pagination substrate (`P2X-QRY-*`).
4. Discovery command rollouts (`P2X-SRCH-*`, `P2X-SPK-*`).
5. Event transport/runtime/persistence (`P2X-EVT-*`, `P2X-STR-*`).
6. Host core workflows (`P2X-HOST-01..04`, `P2X-HOST-09`, `P2X-HOST-10`).
7. Host advanced workflows (`P2X-HOST-05..08`, `P2X-HOST-11`, `P2X-HOST-12`).
8. Late observability and contract fixtures (`P2X-OBS-02/03`, `P2X-CON-*`).
9. CI gates and docs (`P2X-CI-01`, `P2X-DOC-*`).
10. Release checklist commits (`P2X-REL-*`).

---

## 14. Risk Register

1. **Risk:** Search quality drift and low precision.
   1. **Mitigation:** relevance fixtures and thresholded integration tests (`P2X-SRCH-06`).
2. **Risk:** Event listener duplicate or lost processing.
   1. **Mitigation:** ingress contract + dedupe + checkpoint + DLQ + ack/nack state machine (`P2X-EVT-01..11`).
3. **Risk:** Host mutations cause unintended destructive changes.
   1. **Mitigation:** confirm policy, dry-run, idempotency, safety checklist (`P2X-GOV-03`, `P2X-HOST-*`).
4. **Risk:** Contract drift from rapid feature expansion.
   1. **Mitigation:** staged schema fixtures and CI gates (`P2X-CON-*`, `P2X-CI-01`).
5. **Risk:** Local index/event storage security posture regression.
   1. **Mitigation:** encryption + fallback controls + security tests (`P2X-SRCH-05`, `P2X-EVT-05`).
6. **Risk:** Performance degradation under scale.
   1. **Mitigation:** SLO tests and soak benchmarks (`section 12.4`).
7. **Risk:** Upstream API variability across tenants.
   1. **Mitigation:** capability detection and deterministic fallback/errors (`P2X-CAP-*`, `P2X-SRCH-03`, `P2X-HOST-08`).
8. **Risk:** Local store migrations fail and strand profiles.
   1. **Mitigation:** version markers + rollback-safe migration tests (`P2X-STR-01`, `P2X-STR-02`).
9. **Risk:** Partial rollout requires fast rollback between `1.3` and `1.2`.
   1. **Mitigation:** explicit rollback drill and documented procedure (`P2X-REL-03`).
10. **Risk:** Idempotency misuse creates duplicate mutations on retries.
   1. **Mitigation:** explicit key policy + required modes + reporting (`P2X-HOST-10`).
11. **Risk:** RRULE/invitee scope ambiguity creates inconsistent behavior.
   1. **Mitigation:** constrained RRULE parser and explicit file format tasks (`P2X-HOST-11`, `P2X-HOST-12`).

---

## 15. Acceptance Gates

### Gate A: Discovery + Events (Schema 1.2)

1. All `P2X-PRE-*`, `P2X-CAP-01/02`, `P2X-CFG-*`, `P2X-OBS-01`, `P2X-QRY-*`, `P2X-SRCH-*`, `P2X-SPK-*`, `P2X-EVT-*`, `P2X-STR-*` tasks done.
2. Contract fixtures for 1.2 green.
3. Security tests for search/events green.
4. Performance SLOs for search/listener met.
5. Local store migration and retention checks green.

### Gate B: Host Workflows (Schema 1.3)

1. All `P2X-CAP-03` and `P2X-HOST-*` tasks done.
2. Contract fixtures for 1.3 green.
3. Mutation safety checklist passed.
4. Conflict/idempotency integration tests green.
5. Rollback procedure from `1.3` to `1.2` validated.

### Gate C: Combined GA

1. CI gates switched to blocking mode for both schema tracks.
2. Docs published and reviewed.
3. Go/No-Go approvals recorded for both Gate A and Gate B.
4. Rollback drill artifact attached and approved.

### 15.1 Rollback playbook (1.3 to 1.2)

1. Trigger conditions:
   1. host mutation regression affecting correctness or safety
   2. contract compatibility break detected in production telemetry
2. Procedure:
   1. set `WEBEX_PHASE2X_DISABLE_MUTATIONS=1` in release channel config
   2. roll CLI distribution pointer to latest `1.2`-compatible patch build
   3. run store compatibility check to verify `events/search` paths remain readable
   4. preserve `mutations/*` store for forward re-enable; no destructive cleanup during rollback
3. Validation:
   1. run Gate A smoke suite on rollback candidate
   2. verify no schema `1.3`-only commands are exposed in help output
   3. capture rollback evidence artifact for `P2X-REL-03`.

---

## 16. External Evaluation Checklist

1. Every locked decision maps to at least one task and one test area.
2. Query grammar, pagination, and sorting semantics are fully specified.
3. Event source/transport and processing semantics are explicit and testable.
4. Mutation safety controls are explicit and enforceable in non-interactive mode.
5. Schema/version and exit-code governance are covered with CI gating.
6. Commit strategy is clear and review-friendly.
7. Phase merge rationale and boundaries are explicit.
8. Config/env resolution precedence is fully specified and tested.
9. Local store migration and rollback semantics are explicit and testable.
10. Capability detection exists for every upstream-dependent command family.

---

## 17. Plan Review Log

### Review Pass 1
Gaps found:
1. Missing explicit schema staging between discovery and host features.
2. Insufficient mutation safety defaults.
3. Ambiguous event delivery semantics.

Fixes applied:
1. Added schema 1.2/1.3 staged progression and separate acceptance gates.
2. Added locked decisions for confirm policy, dry-run, idempotency.
3. Added at-least-once + dedupe + DLQ semantics and related tasks.

### Review Pass 2
Gaps found:
1. Search/filter grammar was under-specified.
2. Pagination ergonomics lacked deterministic constraints.
3. Sort behavior lacked tie-breaker definition.

Fixes applied:
1. Added formal filter DSL section with operators and validation behavior.
2. Added `--limit`, `--max-pages`, `--page-token` semantics and task coverage.
3. Added deterministic tie-breaker policy by resource type.

### Review Pass 3
Gaps found:
1. Security model for local transcript index not explicit.
2. Event payload logging redaction scope incomplete.
3. Signature validation not captured.

Fixes applied:
1. Added index encryption/fallback policy and dedicated task `P2X-SRCH-05`.
2. Added locked redaction decision for queries/events/payload snapshots.
3. Added event signature validation requirement and tests.

### Review Pass 4
Gaps found:
1. Performance expectations not measurable.
2. Long-running listener operational behavior unspecified.
3. Contract gate details not tied to release gates.

Fixes applied:
1. Added explicit SLO targets and performance/soak test matrix.
2. Added graceful shutdown/checkpoint behavior and related tasks.
3. Added `P2X-CI-01` and gate-specific readiness criteria.

### Review Pass 5
Gaps found:
1. Task board lacked explicit docs and release closure tasks for each schema cut.
2. External evaluator checklist did not enforce decision-to-task mapping.
3. Out-of-scope boundaries between Phase 2X and Phase 4 were implicit.

Fixes applied:
1. Added `P2X-DOC-01`, `P2X-DOC-02`, `P2X-REL-01`, `P2X-REL-02`.
2. Expanded external evaluation checklist with mapping and merge-boundary checks.
3. Added explicit out-of-scope section and constraints.

### Review Pass 6
Gaps found:
1. Config/env surface was implicit and could not be implemented consistently.
2. Event runtime protocol lacked explicit ack/nack and shutdown details.
3. Error taxonomy for new feature areas was not fixture-governed.

Fixes applied:
1. Added explicit config keys, env vars, and precedence rules (`section 8.1`).
2. Extended event command and semantics with transport/worker/shutdown behavior (`sections 4.3, 4.6`).
3. Added `section 5.4` and task `P2X-CON-04` for deterministic taxonomy governance.

### Review Pass 7
Gaps found:
1. Local store migration/version lifecycle lacked concrete execution tasks.
2. Retention and cleanup behavior existed as policy but not implementation plan.
3. Critical path omitted config/storage foundations.

Fixes applied:
1. Added `section 7.4` migration/retention model and tasks `P2X-STR-01`, `P2X-STR-02`.
2. Added cleanup/migration tests across unit, integration, and security matrices.
3. Updated critical path to include `P2X-CFG-*` and `P2X-STR-*`.

### Review Pass 8
Gaps found:
1. Rollback path between schema `1.3` and `1.2` was insufficiently enforced.
2. Acceptance gates did not require rollback evidence.
3. Risk register under-modeled rollout fallback risk.

Fixes applied:
1. Added locked rollback decision and release task `P2X-REL-03`.
2. Added rollback validation requirements to Gate B and Gate C.
3. Added explicit rollback/migration risks with linked mitigations.

### Review Pass 9
Gaps found:
1. Commit sequence did not include newly introduced config/storage foundations.
2. Gate A task-completion list did not include config/store prerequisites.
3. Event-loss risk mitigation reference omitted `ack/nack` hardening task.

Fixes applied:
1. Updated planned commit sequence to include `P2X-CFG-*` and `P2X-STR-*`.
2. Updated Gate A completion criteria to include config/store lanes.
3. Updated risk mitigation mapping to `P2X-EVT-01..11`.

### Review Pass 10
Gaps found:
1. Event source/ingestion mechanism was ambiguous (polling vs webhook).
2. Webhook signature validation requirements were not tied to source mode.
3. Event lane tasks lacked ingress and registration implementation scope.

Fixes applied:
1. Added explicit event transport contract (`webex-webhook` + `file`) and ingress command surface (`sections 4.3, 4.4`).
2. Added source-specific signature semantics (`section 4.6`).
3. Added event ingress and platform tasks (`P2X-EVT-08..11`).

### Review Pass 11
Gaps found:
1. Error taxonomy lacked explicit mapping to domain/exit/retry behavior.
2. Meta contract rollout timing could break schema 1.2 fixtures.
3. Dry-run and idempotency behavior lacked concrete command/contract semantics.

Fixes applied:
1. Added explicit `error.code -> DomainCode -> exit -> retryable` mapping (`section 5.4`).
2. Moved `P2X-OBS-01` to Sprint 0 and added compatibility semantics in `meta` contract (`section 5.2`).
3. Added dry-run contract fields and idempotency command/behavior policy (`sections 4.5, 4.6, 5.3` + tasks `P2X-HOST-09/10`).

### Review Pass 12
Gaps found:
1. Filter DSL precedence/quoting rules were still implicit.
2. RRULE and invitee bulk format support boundaries were under-specified.
3. Parser effort estimate was too low for production-grade behavior.

Fixes applied:
1. Added precedence, literal, escape, and shell guidance rules (`section 6.1`).
2. Added constrained RRULE scope and invitee file format spec (`sections 6.3, 6.4`).
3. Increased parser/test estimates and added dedicated host parsing tasks (`P2X-QRY-01`, `P2X-QRY-04`, `P2X-HOST-11/12`).

### Review Pass 13
Gaps found:
1. Sprint load and critical path were unrealistic for Host and Events.
2. SQLite concurrency details and key lifecycle were incomplete.
3. Pre-existing phase carryover risks were not explicitly gated.

Fixes applied:
1. Split lanes/sprints, added capability/preflight gates, and rebalanced task board (`section 10`).
2. Added sqlite concurrency model and index key lifecycle sections (`7.5`, `8.2`) plus tasks `P2X-STR-03`, `P2X-SRCH-08`.
3. Added readiness gate section with hard stop rule and carryover tasks (`section 0`, `P2X-PRE-*`).

### Review Pass 14
Gaps found:
1. `file` event source input path was ambiguous with sink path semantics.
2. Capability error taxonomy was incomplete for host/event families.
3. Contracts lane lacked explicit task to add new DomainCode/runtime mappings.

Fixes applied:
1. Added explicit `--source-path` for `event listen` file-source mode and clarified transport contract (`section 4.3/4.4`).
2. Expanded capability error families and explicit mappings (`section 5.4`).
3. Added `P2X-CON-05` for DomainCode and mapping implementation completeness.

### Review Pass 15
Gaps found:
1. Event ingress versus listener ownership was still ambiguous and the durable queue store was implied but not specified.
2. Mutation/idempotency policy did not match template and recurrence command surfaces.
3. `--case-sensitive`, `--force-replay`, and transcript index key rotation were referenced elsewhere but absent from the command surface.
4. Readiness status was stronger than the explicit traceability evidence shown.

Fixes applied:
1. Clarified ingress/listener responsibilities, queue-backed semantics, and durable queue storage (`sections 3.42, 4.3, 4.4, 4.6, 7.2, 7.3, 7.5`).
2. Added idempotency coverage to all mutating template/recurrence commands and aligned task definitions (`sections 4.5, 10`).
3. Added the missing command flags/commands and related test coverage (`sections 4.1, 4.3, 6.1, 12`).
4. Replaced the traceability sample with a broader decision traceability matrix and promoted status to `implementation-ready` (`section 0.3`).

### Final Confidence Check
All identified gaps from internal and external review were addressed with explicit protocol decisions, contract mappings, implementation tasks, dependencies, tests, capacity rebalancing, and readiness gates. The plan now satisfies its blocker-gate standard and is implementation-ready.
