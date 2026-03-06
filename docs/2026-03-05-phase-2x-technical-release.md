# Technical Release Notes

Date: March 5, 2026
Release: Phase 2X
Schema: 1.3

## Summary

Phase 2X extends the CLI from Phase 1 artifact retrieval into a broader meetings operations platform. The release adds eventing, host mutation workflows, transcript local indexing, shared search semantics, and expanded contract/test coverage.

## Delivered areas

### Eventing

- `webex event ingress run`
  - local webhook receiver
  - optional upstream registration reconciliation
  - queue-backed ingestion
- `webex event listen`
  - file and local queue sources
  - checkpoint-based resume
  - DLQ handoff and replay paths
- `webex event replay`
  - queue replay from DLQ

### Search

- `meeting search`
- `recording search`
- `transcript search`
- shared query/filter/sort/pagination substrate

### Transcript operations

- `transcript segments`
- `transcript speakers`
- `transcript index rebuild`
- `transcript index key rotate`
- encrypted local transcript index fallback

### Host workflows

- meeting create/update/cancel
- invitee add/remove/list
- template application
- recurrence create/update/cancel
- dry-run and idempotency support on mutation surfaces

### Contract/runtime

- schema 1.3 output envelopes
- additive `meta.profile` and `meta.command_mode`
- explicit non-interactive runtime handling
- expanded capability and error-domain mapping

## Final hardening fixes in this release

1. Webhook signature enforcement
   - Missing signature headers are now rejected when ingress secrets are configured.
   - Files:
     - `webex_cli/eventing/store.py`
     - `webex_cli/commands/event.py`

2. Ingress request-size validation
   - Local ingress now rejects malformed and oversized `Content-Length` values.
   - File:
     - `webex_cli/commands/event.py`

3. Webhook registration secret enforcement
   - `event ingress run --register` now requires a non-empty secret.
   - File:
     - `webex_cli/commands/event.py`

4. Exhaustive pagination for reconciliation/list APIs
   - Added paginated collection logic for:
     - `list_webhooks()`
     - `list_invitees()`
     - `list_meeting_templates()`
   - File:
     - `webex_cli/client/api.py`

5. Checksum policy tightening
   - SHA-256 is now the only accepted checksum algorithm for download verification.
   - Files:
     - `webex_cli/utils/files.py`
     - `webex_cli/client/api.py`

6. Packaging fix
   - Added `cryptography` to declared runtime dependencies.
   - File:
     - `pyproject.toml`

7. Test-worktree cleanup
   - Added `temp_work/` to `.gitignore` to stop test artifact leakage.
   - File:
     - `.gitignore`

## Regression coverage added

- ingress rejects missing signature with configured secret
- ingress rejects invalid `Content-Length`
- ingress rejects oversized payloads
- registration requires configured secret
- webhook pagination coverage
- invitee pagination coverage
- meeting-template pagination coverage
- SHA-256-only checksum behavior for recordings

## Verification

Primary verification command:

```powershell
pytest -q
```

Expected result for this release branch after the final fixes:

- full suite passing
- no new contract regressions in touched paths

## Operational notes

- Webhook ingress should be deployed only behind a real HTTPS public endpoint.
- Auto-registration requires the secret environment variable to be populated before startup.
- Existing consumers relying on MD5 checksum metadata should move to SHA-256.
