# Issue #108: Strengthen memory_ingest CI to detect raw SQL interpolation in every Postgres node

## Supervisor Snapshot
- Issue URL: https://github.com/TommyKammy/nexus-ai-orchestrator/issues/108
- Branch: codex/issue-108
- Workspace: .
- Journal: .codex-supervisor/issues/108/issue-journal.md
- Current phase: addressing_review
- Attempt count: 3 (implementation=1, repair=2)
- Last head SHA: 996b396076979413de3832d7765d58422204aa88
- Blocked reason: none
- Last failure signature: PRRT_kwDORd-8zc56Teyy|PRRT_kwDORd-8zc56Tey1
- Repeated failure signature count: 1
- Updated at: 2026-04-11T14:33:10.811Z

## Latest Codex Summary
Validated the two remaining CodeRabbit findings against head `996b396` and confirmed both were still actionable in [scripts/ci/memory_ingest_workflow_check.sh](scripts/ci/memory_ingest_workflow_check.sh): `check_insert_vector_contract()` matched any node named `Insert Vector`, and the generic Postgres-node check only required `queryReplacement` presence instead of verifying bind coverage. The script now filters `Insert Vector` by Postgres node type and statically counts top-level `queryReplacement` array entries against the highest positional placeholder so under-bound parameter lists fail with the workflow path and node name.

Extended [tests/test_memory_ingest_workflow_check.py](tests/test_memory_ingest_workflow_check.py) with regressions for both review threads: one proves a non-Postgres node named `Insert Vector` is ignored, and one proves a two-placeholder query with a one-item replacement array fails with the new binding-count error. Focused verification passed locally after the patch.

Summary: Addressed the two remaining automated review threads by hardening the memory-ingest CI selector and bind-count validation.
State hint: local_review_fix
Blocked reason: none
Tests: `python3 -m unittest -q tests/test_memory_ingest_workflow_check.py`; `bash scripts/ci/memory_ingest_workflow_check.sh`
Next action: Commit and push the review-fix checkpoint on `codex/issue-108`, then monitor PR #110 for refreshed CI/review state.
Failure signature: none

## Active Failure Context
- Category: review
- Summary: 2 unresolved automated review thread(s) remain.
- Reference: https://github.com/TommyKammy/nexus-ai-orchestrator/pull/110#discussion_r3068153956
- Details:
  - scripts/ci/memory_ingest_workflow_check.sh:50 summary=_⚠️ Potential issue_ | _🟠 Major_ **Filter `Insert Vector` by node type here too.** `check_insert_vector_contract()` currently selects every node named `Insert Vector`, while `c... url=https://github.com/TommyKammy/nexus-ai-orchestrator/pull/110#discussion_r3068153956
  - scripts/ci/memory_ingest_workflow_check.sh:100 summary=_⚠️ Potential issue_ | _🟠 Major_ **Presence of `queryReplacement` is weaker than binding validation.** Once `queryReplacement` is non-null, this returns without checking that t... url=https://github.com/TommyKammy/nexus-ai-orchestrator/pull/110#discussion_r3068153961

## Codex Working Notes
### Current Handoff
- Hypothesis: The remaining review risk was not just missing workflow coverage; the CI guard could also inspect the wrong `Insert Vector` node by name and allow under-bound `queryReplacement` arrays to pass.
- What changed: Tightened `check_insert_vector_contract()` to select only `n8n-nodes-base.postgres` nodes named `Insert Vector`, added static bind counting for parameterized `queryReplacement` array expressions, and extended the focused unit tests to cover both the selector hardening and the missing-binding failure mode.
- Current blocker: none
- Next exact step: Push the current checkpoint and watch PR #110 for refreshed CI plus updated review-thread state.
- Verification gap: Focused verification passed for the CI guard and its regression tests; broader repo-wide test/lint suites remain unrun in this turn.
- Files touched: scripts/ci/memory_ingest_workflow_check.sh; tests/test_memory_ingest_workflow_check.py; .codex-supervisor/issues/108/issue-journal.md
- Rollback concern: The `Insert Facts` rewrite now depends on Postgres `unnest` with aligned arrays from n8n `queryReplacement`, so a rollback should keep the script and workflow SQL in sync.
- Last focused command: `bash scripts/ci/memory_ingest_workflow_check.sh`
### Scratchpad
- Local review triage: the stale issue-journal status comment is already obsolete in the live file; the actionable local fixes were PRRT_kwDORd-8zc56Tc8K, PRRT_kwDORd-8zc56Tc8N, PRRT_kwDORd-8zc56Tc8O, PRRT_kwDORd-8zc56Tc8P, and PRRT_kwDORd-8zc56Tc8R.
- Commands run this turn: `python3 -m unittest -q tests/test_memory_ingest_workflow_check.py`; `bash scripts/ci/memory_ingest_workflow_check.sh`; `git diff -- scripts/ci/memory_ingest_workflow_check.sh tests/test_memory_ingest_workflow_check.py`.
