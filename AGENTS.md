# Code Review Rules

- Do separate passes for correctness, security, packaging/imports, pagination/data volume, and tests.
- Do not trust green tests alone; inspect high-risk paths directly.
- Treat missing tests for risky behavior as findings, not optional follow-up.
- Verify install-time dependencies and import paths for newly added modules.
- For ingress code, always check auth/signature enforcement, missing-auth behavior, and body-size limits.
- For list/reconcile APIs, always verify pagination behavior and full-inventory callers.
- For mutation paths, verify dry-run stays local and idempotency is actually sent downstream.
- Do not say "no more bugs" unless all review passes were completed and re-verified.
