# Issue #108: Strengthen memory_ingest CI to detect raw SQL interpolation in every Postgres node

## Supervisor Snapshot
- Issue URL: https://github.com/TommyKammy/nexus-ai-orchestrator/issues/108
- Branch: codex/issue-108
- Workspace: .
- Journal: .codex-supervisor/issues/108/issue-journal.md
- Current phase: reproducing
- Attempt count: 1 (implementation=1, repair=0)
- Last head SHA: d6ac7291299d7ba3b1148c078cc07f74681d589c
- Blocked reason: none
- Last failure signature: none
- Repeated failure signature count: 0
- Updated at: 2026-04-11T14:05:09.248Z

## Latest Codex Summary
- None yet.

## Active Failure Context
- None recorded.

## Codex Working Notes
### Current Handoff
- Hypothesis: The CI guard only inspected `Insert Vector` in two workflows, so raw `{{ ... }}` interpolation in other memory-ingest Postgres nodes could ship undetected.
- What changed: Added a focused regression test for the shell check, expanded `memory_ingest_workflow_check.sh` to inspect every Postgres node across the three covered memory-ingest workflows, parameterized `Insert Facts` / `Insert Audit` in both main workflows plus `Insert Facts` / `Insert Vector` / `Insert Audit` in the cached workflow, committed the result as `def7764`, pushed `codex/issue-108`, and opened draft PR #110.
- Current blocker: none
- Next exact step: Monitor PR #110 checks and address any CI or review feedback if it appears.
- Verification gap: Focused verification passed; broader lint/test suites have not been run in this turn.
- Files touched: scripts/ci/memory_ingest_workflow_check.sh; tests/test_memory_ingest_workflow_check.py; n8n/workflows/01_memory_ingest.json; n8n/workflows-v3/01_memory_ingest.json; n8n/workflows/01_memory_ingest_v3_cached.json; .codex-supervisor/issues/108/issue-journal.md
- Rollback concern: The `Insert Facts` rewrite now depends on Postgres `unnest` with aligned arrays from n8n `queryReplacement`, so a rollback should keep the script and workflow SQL in sync.
- Last focused command: gh pr create --draft --base main --head codex/issue-108 --title "Strengthen memory_ingest SQL interpolation guard" --body ...
### Scratchpad
- Keep this section short. The supervisor may compact older notes automatically.
