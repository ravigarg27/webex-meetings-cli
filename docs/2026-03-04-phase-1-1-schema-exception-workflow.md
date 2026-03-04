# Schema-Major Exception Workflow

Date: 2026-03-04

Use this process for any intentional breaking contract change.

## Required Inputs

1. Problem statement and why non-breaking alternatives are insufficient.
2. Exact contract diff:
   1. Envelope keys.
   2. Field type/meaning changes.
   3. Exit-code impacts.
3. Migration plan for automation users.
4. Rollback strategy.

## Approval Sequence

1. Owner proposes exception PR with:
   1. Updated schema version.
   2. Updated fixtures.
   3. Updated docs/release notes.
2. At least one maintainer + one reviewer approval required.
3. Exception must be merged before RC cut.

## Validation Requirements

1. Contract fixture tests updated and passing.
2. Exit-code matrix reviewed and passing.
3. Explicit changelog entry marked `BREAKING`.
