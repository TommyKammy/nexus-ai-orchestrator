# Issue #108: Strengthen memory_ingest CI to detect raw SQL interpolation in every Postgres node

## Supervisor Snapshot
- Issue URL: https://github.com/TommyKammy/nexus-ai-orchestrator/issues/108
- Branch: codex/issue-108
- Workspace: .
- Journal: .codex-supervisor/issues/108/issue-journal.md
- Current phase: addressing_review
- Attempt count: 2 (implementation=1, repair=1)
- Last head SHA: 27ed3ed0637a7e97672e6f41b1f3fae6da0ea109
- Blocked reason: none
- Last failure signature: PRRT_kwDORd-8zc56Tc8G|PRRT_kwDORd-8zc56Tc8K|PRRT_kwDORd-8zc56Tc8N|PRRT_kwDORd-8zc56Tc8O|PRRT_kwDORd-8zc56Tc8P|PRRT_kwDORd-8zc56Tc8R
- Repeated failure signature count: 1
- Updated at: 2026-04-11T14:23:41.426Z

## Latest Codex Summary
Expanded `scripts/ci/memory_ingest_workflow_check.sh` to inspect every Postgres node in the covered memory-ingest workflows, fail on raw `{{ ... }}` or `${ ... }}` interpolation, require positional placeholders with `queryReplacement` when runtime values are bound, and report the exact workflow plus node on failure. I kept the stronger `Insert Vector` metadata contract for the two full memory-ingest workflows and added a focused regression test in [tests/test_memory_ingest_workflow_check.py](tests/test_memory_ingest_workflow_check.py).

I also parameterized the remaining raw-SQL nodes in [n8n/workflows/01_memory_ingest.json](n8n/workflows/01_memory_ingest.json), [n8n/workflows-v3/01_memory_ingest.json](n8n/workflows-v3/01_memory_ingest.json), and [n8n/workflows/01_memory_ingest_v3_cached.json](n8n/workflows/01_memory_ingest_v3_cached.json) by replacing interpolated inserts with placeholder-based queries plus `queryReplacement`. The branch is pushed, and draft PR #110 is open: `https://github.com/TommyKammy/nexus-ai-orchestrator/pull/110`.

Summary: Tightened the memory-ingest CI guard across all covered Postgres nodes, added a focused regression test, parameterized the remaining unsafe workflow SQL, pushed `codex/issue-108`, and opened draft PR #110.
State hint: draft_pr
Blocked reason: none
Tests: `python3 -m unittest -q tests/test_memory_ingest_workflow_check.py`; `bash scripts/ci/memory_ingest_workflow_check.sh`
Next action: Monitor draft PR #110 checks and address any CI or review feedback if it appears.
Failure signature: PRRT_kwDORd-8zc56Tc8G|PRRT_kwDORd-8zc56Tc8K|PRRT_kwDORd-8zc56Tc8N|PRRT_kwDORd-8zc56Tc8O|PRRT_kwDORd-8zc56Tc8P|PRRT_kwDORd-8zc56Tc8R

## Active Failure Context
- Category: review
- Summary: 6 unresolved automated review thread(s) remain.
- Reference: https://github.com/TommyKammy/nexus-ai-orchestrator/pull/110#discussion_r3068144521
- Details:
  - .codex-supervisor/issues/108/issue-journal.md:10 summary=_⚠️ Potential issue_ | _🟡 Minor_ **Update supervisor status fields to current PR state** Line 8 and Line 10 look stale against the current tracking context (`waiting_ci` and he... url=https://github.com/TommyKammy/nexus-ai-orchestrator/pull/110#discussion_r3068144521
  - n8n/workflows-v3/01_memory_ingest.json:159 summary=_⚠️ Potential issue_ | _🟠 Major_ **Normalize invalid `confidence` values before building the array.** This mapping can still produce `NaN` for explicit-source facts with malfor... url=https://github.com/TommyKammy/nexus-ai-orchestrator/pull/110#discussion_r3068144525
  - n8n/workflows-v3/01_memory_ingest.json:257 summary=_⚠️ Potential issue_ | _🟡 Minor_ **Use the canonical policy decision token in the fallback.** `Check Policy` emits `allow`, but this fallback writes `allowed`. url=https://github.com/TommyKammy/nexus-ai-orchestrator/pull/110#discussion_r3068144530
  - n8n/workflows/01_memory_ingest_v3_cached.json:180 summary=_⚠️ Potential issue_ | _🟠 Major_ **Guard against `NaN` in the bound confidence array.** The explicit-source path can still pass malformed confidence values through, and this `N... url=https://github.com/TommyKammy/nexus-ai-orchestrator/pull/110#discussion_r3068144531
  - n8n/workflows/01_memory_ingest.json:121 summary=_⚠️ Potential issue_ | _🟠 Major_ **Harden `confidence` coercion before binding.** For `source === 'explicit'`, a fact with a non-numeric confidence can survive validation here,... url=https://github.com/TommyKammy/nexus-ai-orchestrator/pull/110#discussion_r3068144533

## Codex Working Notes
### Current Handoff
- Hypothesis: The CI guard only inspected `Insert Vector` in two workflows, so raw `{{ ... }}` interpolation in other memory-ingest Postgres nodes could ship undetected.
- What changed: Applied the current PR review fixes on top of `def7764`: hardened all three `Insert Facts` confidence arrays against `NaN`, changed the v3 audit fallback token from `allowed` to `allow`, tightened the CI `Insert Vector` contract to require an actual `.json.content_hash` bind, and extended the focused regression test to prove the stricter failure mode.
- Current blocker: none
- Next exact step: Commit these review fixes on `codex/issue-108`, then push the branch and refresh PR #110 for another review/CI pass.
- Verification gap: Focused verification passed again; broader lint/test suites have still not been run in this turn.
- Files touched: scripts/ci/memory_ingest_workflow_check.sh; tests/test_memory_ingest_workflow_check.py; n8n/workflows/01_memory_ingest.json; n8n/workflows-v3/01_memory_ingest.json; n8n/workflows/01_memory_ingest_v3_cached.json; .codex-supervisor/issues/108/issue-journal.md
- Rollback concern: The `Insert Facts` rewrite now depends on Postgres `unnest` with aligned arrays from n8n `queryReplacement`, so a rollback should keep the script and workflow SQL in sync.
- Last focused command: `bash scripts/ci/memory_ingest_workflow_check.sh`
### Scratchpad
- Local review triage: the stale issue-journal status comment is already obsolete in the live file; the actionable local fixes were PRRT_kwDORd-8zc56Tc8K, PRRT_kwDORd-8zc56Tc8N, PRRT_kwDORd-8zc56Tc8O, PRRT_kwDORd-8zc56Tc8P, and PRRT_kwDORd-8zc56Tc8R.
- Commands run this turn: `python3 -m unittest -q tests/test_memory_ingest_workflow_check.py`; `bash scripts/ci/memory_ingest_workflow_check.sh`.
