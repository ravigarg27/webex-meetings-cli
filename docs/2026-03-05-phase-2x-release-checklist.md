# Phase 2X Release Checklist

## Gate A: Discovery + Events (`1.2`)

1. `pytest tests/contracts -q`
2. `pytest tests/unit/test_event_commands.py tests/unit/test_event_store.py tests/unit/test_transcript_index_commands.py -q`
3. Verify README command reference includes discovery and events
4. Verify schema fixture files exist:
   1. `tests/contracts/fixtures/envelope_contract_v1_2.json`
   2. `tests/contracts/fixtures/exit_code_matrix_v1_2.json`
5. Verify event ingress registration path:
   1. list/create/update webhook client methods available
   2. deterministic capability fallback exists when upstream support is missing

## Gate B: Host Workflows (`1.3`)

1. `pytest tests/unit/test_meeting_host_commands.py -q`
2. `pytest tests/contracts -q`
3. Verify host operator guide exists
4. Verify schema fixture files exist:
   1. `tests/contracts/fixtures/envelope_contract_v1_3.json`
   2. `tests/contracts/fixtures/exit_code_matrix_v1_3.json`
   3. `tests/contracts/fixtures/error_codes_v1_3.json`
5. Verify current runtime schema version is `1.3`

## CI Gate Policy

CI behavior is implemented in `.github/workflows/ci.yml`:

1. contract tests run in `warn` mode on non-release branches
2. contract tests run in `block` mode on release branches and version tags

## Go/No-Go evidence

Record:

1. full `pytest -q` output
2. contract test output
3. release candidate schema version
4. rollback validation notes
