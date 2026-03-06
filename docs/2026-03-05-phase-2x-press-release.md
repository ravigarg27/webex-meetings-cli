# Press Release

Date: March 5, 2026

## Webex Meetings CLI Ships Phase 2X

The Webex Meetings CLI now includes the full Phase 2X release: event ingestion, search and transcript indexing, host workflows, stronger JSON contracts, and tighter operational controls for production use.

This release expands the CLI from artifact retrieval into a broader meetings operations surface. Teams can now search meetings, recordings, and transcripts with consistent filtering and pagination semantics, manage host-side workflows, run local event ingestion with replay support, and use an encrypted local transcript index when upstream transcript discovery is limited.

## Highlights

- Event ingestion and replay
  - Local webhook ingress with queueing, checkpoints, replay, and dead-letter handling
  - Webhook registration reconciliation for supported profiles
- Search and transcript workflows
  - Shared query/filter/sort substrate across meetings, recordings, and transcripts
  - Transcript segment and speaker views
  - Encrypted local transcript index with rebuild and key rotation
- Host operations
  - Meeting create, update, cancel, invitee, template, and recurrence workflows
  - Dry-run and idempotency support for mutating commands
- Contract and reliability improvements
  - Schema 1.3 envelopes
  - Expanded capability/error handling
  - Rollout, rollback, and operator guidance artifacts

## Security and hardening updates

This release also closes several operational and security gaps identified during review:

- Webhook ingress now fails closed when a secret is configured and the signature header is missing or invalid.
- Local ingress now enforces bounded request sizes and rejects malformed `Content-Length` values.
- Webhook auto-registration now requires a non-empty secret.
- Pagination is now exhaustive for webhook, invitee, and meeting-template inventory calls.
- Checksum verification now uses SHA-256 only.
- `cryptography` is now declared as a required install dependency.

## Availability

Phase 2X is available in the current project branch and is covered by the project test suite and contract fixtures.
