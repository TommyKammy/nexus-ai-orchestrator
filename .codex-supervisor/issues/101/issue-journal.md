# Issue #101: Parameterize workflow SQL and eliminate raw string interpolation

## Supervisor Snapshot
- Issue URL: https://github.com/TommyKammy/nexus-ai-orchestrator/issues/101
- Branch: codex/issue-101
- Workspace: .
- Journal: .codex-supervisor/issues/101/issue-journal.md
- Current phase: reproducing
- Attempt count: 1 (implementation=1, repair=0)
- Last head SHA: 7f5735110f3096ffe82e78b06078c69680250398
- Blocked reason: none
- Last failure signature: none
- Repeated failure signature count: 0
- Updated at: 2026-04-11T07:46:32.184Z

## Latest Codex Summary
- Added a focused policy registry SQL check, reproduced raw interpolation in `06_policy_registry_upsert.json`, then parameterized the dynamic policy registry and candidate seed Postgres queries with `queryReplacement`.
- Updated workflow validation CI to run the new focused check and documented the no-raw-SQL-interpolation rule in `n8n/workflows/README.md`.
- Focused verification passed: `bash scripts/ci/policy_registry_workflow_check.sh`, `bash scripts/ci/audit_append_workflow_check.sh`, `bash scripts/ci/vector_search_workflow_check.sh`, and `bash scripts/ci/workflow_schema_check.sh`.

## Active Failure Context
- None recorded.

## Codex Working Notes
### Current Handoff
- Hypothesis: Policy registry mutation and lookup workflows are still vulnerable because they build SQL with template interpolation instead of Postgres placeholders and `queryReplacement`.
- What changed: Added `scripts/ci/policy_registry_workflow_check.sh`; wired it into `.github/workflows/validate-workflows.yml`; parameterized dynamic SQL in `06_policy_registry_upsert.json`, `07_policy_registry_publish.json`, `09_policy_registry_get.json`, `11_policy_candidate_seed.json`, and `12_policy_registry_delete.json`; documented the workflow authoring rule in `n8n/workflows/README.md`.
- Current blocker: none.
- Next exact step: Commit the hardened workflows on `codex/issue-101`, then open or update a draft PR if no PR exists yet.
- Verification gap: Did not run `scripts/ci/n8n_import_test.sh` or the full compose journey; focused workflow checks and schema validation only.
- Files touched: `.github/workflows/validate-workflows.yml`, `scripts/ci/policy_registry_workflow_check.sh`, `n8n/workflows-v3/06_policy_registry_upsert.json`, `n8n/workflows-v3/07_policy_registry_publish.json`, `n8n/workflows-v3/09_policy_registry_get.json`, `n8n/workflows-v3/11_policy_candidate_seed.json`, `n8n/workflows-v3/12_policy_registry_delete.json`, `n8n/workflows/README.md`.
- Rollback concern: Low; changes are limited to Postgres node query strings and `queryReplacement` payload bindings for the affected workflows.
- Last focused command: `bash scripts/ci/workflow_schema_check.sh`
### Scratchpad
- Keep this section short. The supervisor may compact older notes automatically.
