# Issue #103: Codify and verify branch protection required check names

## Supervisor Snapshot
- Issue URL: https://github.com/TommyKammy/nexus-ai-orchestrator/issues/103
- Branch: codex/issue-103
- Workspace: .
- Journal: .codex-supervisor/issues/103/issue-journal.md
- Current phase: reproducing
- Attempt count: 1 (implementation=1, repair=0)
- Last head SHA: 5ebf4729ed4c5850efad2f1244ab0f0267cfb8bd
- Blocked reason: none
- Last failure signature: none
- Repeated failure signature count: 0
- Updated at: 2026-04-11T01:01:02.551Z

## Latest Codex Summary
- Added a repo-local canonical manifest for `main` branch protection required checks, a validation script/wrapper, focused unittest coverage, and operator docs/runbook updates so stale `Workflow / job` names fail locally before merge is blocked.

## Active Failure Context
- Reproduced initial drift with `bash scripts/ci/branch_protection_check_names_check.sh`, which failed on stale checklist references like `Quality Gates / quality-gates` instead of the exact reported check names.

## Codex Working Notes
### Current Handoff
- Hypothesis: PR merge blocking came from branch protection expecting exact short check names while repo docs still advertised stale `Workflow / job` display strings and there was no local drift detector.
- What changed: Added `scripts/ci/branch_protection_required_checks.json`, `scripts/check_branch_protection_check_names.py`, `scripts/ci/branch_protection_check_names_check.sh`, `tests/test_branch_protection_check_names.py`, updated `docs/production-readiness-checklist.md`, `docs/release-process.md`, `README.md`, and added `docs/branch-protection-checks-runbook.md`.
- Current blocker: none
- Next exact step: Commit the checkpoint on `codex/issue-103`; PR opening can happen after commit if needed.
- Verification gap: No GitHub-side branch protection inspection was performed locally; verification is repo-local drift detection plus existing workflow/build checks.
- Files touched: README.md; docs/production-readiness-checklist.md; docs/release-process.md; docs/branch-protection-checks-runbook.md; scripts/check_branch_protection_check_names.py; scripts/ci/branch_protection_check_names_check.sh; scripts/ci/branch_protection_required_checks.json; tests/test_branch_protection_check_names.py; .codex-supervisor/issues/103/issue-journal.md
- Rollback concern: Low; changes are additive except doc wording updates, and the new validation only reads repo files.
- Last focused command: bash scripts/ci/build.sh
### Scratchpad
- Keep this section short. The supervisor may compact older notes automatically.
