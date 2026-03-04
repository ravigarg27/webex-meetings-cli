# Phase 1.1 Release Checklist

Date: 2026-03-04

## Go/No-Go Checklist

1. Functional
   1. Profile lifecycle commands pass smoke tests.
   2. PAT and OAuth device flow login paths pass.
   3. OAuth refresh and invalid-state handling pass.
   4. Transcript batch concurrency + fail-fast behavior pass.
2. Security
   1. Redaction tests pass.
   2. CI-strict fallback policy tests pass.
   3. Profile isolation tests pass.
3. Contracts
   1. Envelope fixture suite green.
   2. Exit-code matrix fixture green.
   3. Schema version is `1.1`.
4. CI
   1. Gate mode behavior verified (`warn` pre-RC, `block` RC/GA).
5. Docs
   1. README reflects profile/OAuth/logging/checksum behavior.
   2. Contract addendum, release policy, and decision notes published.

## Decision Record

1. Go/No-Go reviewer:
2. Date:
3. Outcome:
4. Notes:
