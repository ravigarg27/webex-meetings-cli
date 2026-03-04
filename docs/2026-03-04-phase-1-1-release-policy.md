# Phase 1.1 Release Policy

Date: 2026-03-04

## RC Freeze

1. RC freeze date: **March 20, 2026**.
2. RC branch naming: `release/1.1.x`.
3. Only bug fixes, contract fixes, and release-note updates are allowed on RC branches.

## Contract Gate Modes

1. Pre-RC branches: `warn` mode.
2. RC branches (`release/*`) and GA tags (`v*`): `block` mode.
3. CI implementation:
   1. Core tests always blocking.
   2. Contract tests respect gate mode:
      1. `warn`: emit warning but do not fail workflow.
      2. `block`: fail workflow on contract drift.

## GA Criteria

1. Schema version remains `1.1`.
2. Contract fixture suite green.
3. Exit-code matrix unchanged.
4. Security redaction and fallback-policy tests green.
