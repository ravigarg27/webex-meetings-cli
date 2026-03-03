# Webex CLI Implementation Commit Strategy

Date: 2026-03-03  
Status: Active

## Goals

1. Keep every commit buildable and reviewable.
2. Minimize mixed-scope changes.
3. Require review checks before moving to next milestone.

## Commit Rules

1. One milestone or sub-milestone per commit.
2. Commit message format:
   - `chore: ...` for scaffolding/config
   - `feat: ...` for behavior changes
   - `test: ...` for test-only additions
   - `fix: ...` for contract/bug corrections
3. No unrelated file changes in a commit.
4. No force-push or amend unless explicitly requested.

## Review Gate Before Next Commit

For each milestone:

1. Inspect `git diff --stat` and focused `git diff` on touched files.
2. Validate error handling and exit code behavior against spec.
3. Validate JSON envelope shape for commands touched.
4. Validate command signatures and flags against spec.
5. Ensure tests added or updated for new behavior.

## Verification Expectations

1. Unit tests for all newly added behavior.
2. Integration tests for API adapter behavior where relevant.
3. CLI smoke e2e for affected command groups.
4. If runtime tools are unavailable (for example Python missing), document exact commands required to verify once available.

