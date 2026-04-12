# Issue #116: Move tenant-facing SQL out of n8n workflows into dedicated services

## Supervisor Snapshot
- Issue URL: https://github.com/TommyKammy/nexus-ai-orchestrator/issues/116
- Branch: codex/issue-116
- Workspace: .
- Journal: .codex-supervisor/issues/116/issue-journal.md
- Current phase: addressing_review
- Attempt count: 2 (implementation=1, repair=1)
- Last head SHA: b60ade095accbd845fcc5fce377af3f96c116cb3
- Blocked reason: none
- Last failure signature: PRRT_kwDORd-8zc56Xn6g
- Repeated failure signature count: 1
- Updated at: 2026-04-12T13:43:39.736Z

## Latest Codex Summary
Added a focused reproducer for the architectural boundary in commit `b60ade0` (`Add tenant workflow service boundary reproducer`). The new guard is `scripts/ci/tenant_workflow_service_boundary_check.sh`, backed by `scripts/check_tenant_workflow_service_boundary.py`, with unit coverage in [tests/test_tenant_workflow_service_boundary_check.py](tests/test_tenant_workflow_service_boundary_check.py:1).

The guard reproduces the issue against the live repo by failing on direct Postgres nodes across the canonical v3 tenant-facing workflows, including `01_memory_ingest`, `02_vector_search`, `03_audit_append`, `04_executor_dispatch`, `05_policy_approval`, and the `06-12` policy-registry workflows. The focused unit test passes locally via `unittest`; host `pytest` was not installed, so I used the standard library runner instead. I also updated the local issue journal’s Codex Working Notes with the hypothesis, failure signature, and next step.

Summary: Added and committed a narrow service-boundary reproducer that fails on current v3 workflows still using direct Postgres nodes.
State hint: reproducing
Blocked reason: none
Tests: `python3 -m unittest -q tests.test_tenant_workflow_service_boundary_check` (passed); `bash scripts/ci/tenant_workflow_service_boundary_check.sh` (fails on current repo as intended)
Next action: implement dedicated internal service endpoints for memory, audit, and policy-registry access, then replace the flagged v3 Postgres nodes with service-call nodes and rerun the new boundary check
Failure signature: PRRT_kwDORd-8zc56Xn6g

## Active Failure Context
- Category: review
- Summary: 1 unresolved automated review thread(s) remain.
- Reference: https://github.com/TommyKammy/nexus-ai-orchestrator/pull/121#discussion_r3069535435
- Details:
  - scripts/ci/tenant_workflow_service_boundary_check.sh:4 summary=_⚠️ Potential issue_ | _🟡 Minor_ **Make script path resolution independent of current working directory.** Line 4 relies on being executed from repo root. url=https://github.com/TommyKammy/nexus-ai-orchestrator/pull/121#discussion_r3069535435

## Codex Working Notes
### Current Handoff
- Hypothesis: The remaining blocker is still architectural, not harness-related: the shell wrapper path issue is fixed, and the boundary check now fails from any cwd only because canonical v3 tenant-facing workflows still embed direct `n8n-nodes-base.postgres` nodes.
- What changed: Updated `scripts/ci/tenant_workflow_service_boundary_check.sh` to resolve `REPO_ROOT` from `BASH_SOURCE[0]` and pass `--repo-root` explicitly, and extended `tests/test_tenant_workflow_service_boundary_check.py` with a subprocess regression test that invokes the wrapper from outside the repo.
- Current blocker: None. Reproduction is stable and points at workflow/service refactoring work rather than a flaky test harness.
- Next exact step: Implement dedicated HTTP service endpoints for memory, audit, and policy-registry access, then replace the flagged Postgres nodes in `n8n/workflows-v3/01-12` with service-call nodes and rerun the new boundary check.
- Verification gap: Full build/test gates not run yet; focused verification covered only the boundary checker unit suite and direct wrapper invocations from repo-root and a temporary external cwd.
- Files touched: `.codex-supervisor/issues/116/issue-journal.md`, `scripts/check_tenant_workflow_service_boundary.py`, `scripts/ci/tenant_workflow_service_boundary_check.sh`, `tests/test_tenant_workflow_service_boundary_check.py`
- Rollback concern: Low. Changes are additive and isolated to a new reproducing guard plus journal notes.
- Last focused command: `tmpdir=$(mktemp -d) && cd "$tmpdir" && bash /Users/tsinfra/Dev/nexus-ai-orchestrator/nexus-ai-orchestrator-worktree/issue-116/scripts/ci/tenant_workflow_service_boundary_check.sh`
### Scratchpad
- Keep this section short. The supervisor may compact older notes automatically.
- Failure signature captured: `tenant_workflow_service_boundary_postgres_nodes`
- 2026-04-12: Addressed review thread `PRRT_kwDORd-8zc56Xn6g` locally by making the shell wrapper cwd-independent; focused verification confirmed the wrapper now executes the checker correctly from both repo-root and an external working directory.
