# Phase 2X Rollback Drill

## Goal

Validate rollback from schema `1.3` operational state to `1.2`-compatible runtime expectations without local store corruption.

## Preconditions

1. profile-scoped event and search stores exist
2. mutation idempotency cache exists
3. contract fixtures for `1.2` and `1.3` are present

## Drill steps

1. Capture current verification evidence:
   1. `pytest -q`
   2. `pytest tests/contracts -q`
2. Confirm host-only command surface that would disappear under `1.2`:
   1. `meeting create|update|cancel`
   2. `meeting invitee *`
   3. `meeting template *`
   4. `meeting recurrence *`
3. Confirm event and search stores are readable without host store initialization
4. Simulate rollback decision:
   1. keep local `events/` and `search/` stores
   2. stop invoking host mutation command paths
   3. retain `mutations/` store data for later forward restore
5. Verify `1.2` fixture expectations remain valid:
   1. envelope shape
   2. exit-code matrix
   3. event and discovery command behavior

## Success criteria

1. no event or search store migration is required to continue operating discovery/event commands
2. host-only contracts are isolated to schema `1.3`
3. contract tests for historical fixtures remain loadable

## Notes

This repository keeps staged fixture files for `1.1`, `1.2`, and `1.3` to preserve rollback evidence even when the live runtime is at `1.3`.
