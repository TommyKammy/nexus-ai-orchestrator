# Issue #103: Codify and verify branch protection required check names

## Supervisor Snapshot
- Issue URL: https://github.com/TommyKammy/nexus-ai-orchestrator/issues/103
- Branch: codex/issue-103
- Workspace: .
- Journal: .codex-supervisor/issues/103/issue-journal.md
- Current phase: addressing_review
- Attempt count: 4 (implementation=2, repair=2)
- Last head SHA: 072c31c885a8153ef9045988f8af249d6f20b6eb
- Blocked reason: none
- Last failure signature: PRRT_kwDORd-8zc56RD68
- Repeated failure signature count: 1
- Updated at: 2026-04-11T01:30:25.977Z

## Latest Codex Summary
Updated [scripts/check_branch_protection_check_names.py](scripts/check_branch_protection_check_names.py) and [tests/test_branch_protection_check_names.py](tests/test_branch_protection_check_names.py) to address the remaining unresolved CodeRabbit thread on stale doc detection. The validator now flags any legacy `workflow-like label / <required-check>` reference in docs instead of only aliases derived from the current workflow name, and `legacy_doc_aliases_for_required_checks` now iterates every producer path for a required check rather than only the first one.

The new regression coverage proves the rename case that motivated the review: docs containing an old alias like `Old Validate Pipeline / validate` now fail even when the current workflow is still named `Validate workflows`. Local verification passed with `python3 -m unittest -v tests.test_branch_protection_check_names`, `bash scripts/ci/branch_protection_check_names_check.sh`, `bash scripts/ci/workflow_schema_check.sh`, and `bash scripts/ci/build.sh`; `build.sh` still emits the existing docker-compose warnings about unset API key env vars and the obsolete compose `version` field, but it did not fail.

Summary: Tightened legacy doc alias detection for renamed workflows and added regression coverage for the remaining PR #105 review thread
State hint: addressing_review
Blocked reason: none
Tests: `gh pr view 105 --repo TommyKammy/nexus-ai-orchestrator --json number,url,isDraft,headRefName,headRefOid,baseRefName,mergeStateStatus,reviewDecision,statusCheckRollup`; `python3 /Users/jp.infra/.codex/plugins/cache/openai-curated/github/fb0a18376bcd9f2604047fbe7459ec5aed70c64b/skills/gh-address-comments/scripts/fetch_comments.py --repo TommyKammy/nexus-ai-orchestrator --pr 105`; `python3 -m unittest -v tests.test_branch_protection_check_names`; `bash scripts/ci/branch_protection_check_names_check.sh`; `bash scripts/ci/workflow_schema_check.sh`; `bash scripts/ci/build.sh`
Next action: Commit and push the local review fix on `codex/issue-103`, then re-check PR #105 review-thread and merge state
Failure signature: PRRT_kwDORd-8zc56RD68

## Active Failure Context
- Category: review
- Summary: 1 unresolved automated review thread(s) remain.
- Reference: https://github.com/TommyKammy/nexus-ai-orchestrator/pull/105#discussion_r3067334489
- Details:
  - scripts/check_branch_protection_check_names.py:191 summary=_⚠️ Potential issue_ | _🟠 Major_ **Don’t key stale-doc detection to the current workflow name only.** Right now the validator only searches docs for exact aliases built from th... url=https://github.com/TommyKammy/nexus-ai-orchestrator/pull/105#discussion_r3067334489

## Codex Working Notes
### Current Handoff
- Hypothesis: PR merge blocking came from branch protection expecting exact short check names while repo docs still advertised stale `Workflow / job` display strings and there was no local drift detector.
- What changed: Kept the earlier parser hardening and additionally changed stale-doc detection so it matches any legacy `label / <required-check>` form in docs, not just aliases built from the current workflow name. `legacy_doc_aliases_for_required_checks` now walks every producer path for a required check, and the tests cover both a renamed-workflow alias in docs and multi-producer alias collection.
- Current blocker: none
- Next exact step: Commit and push the current review fix on `codex/issue-103`, then re-check PR #105 review-thread state and merge status.
- Verification gap: No GitHub-side branch protection inspection was performed locally; verification remains repo-local drift detection plus existing workflow/build checks and pending PR CI.
- Files touched: README.md; docs/production-readiness-checklist.md; docs/release-process.md; docs/branch-protection-checks-runbook.md; scripts/check_branch_protection_check_names.py; scripts/ci/branch_protection_check_names_check.sh; scripts/ci/branch_protection_required_checks.json; tests/test_branch_protection_check_names.py; .codex-supervisor/issues/103/issue-journal.md
- Rollback concern: Low; changes are additive except doc wording updates, and the new validation only reads repo files.
- Last focused command: bash scripts/ci/build.sh
### Scratchpad
- Keep this section short. The supervisor may compact older notes automatically.
- `bash scripts/ci/branch_protection_check_names_check.sh` initially failed because the parser treated nested `with.name` values as job names; direct job-property indentation tracking fixed that false negative.
- Live GitHub thread fetch still shows `PRRT_kwDORd-8zc56RD68` unresolved; the current file still had the rename gap, so the latest fix moved doc detection to a generic `label / required-check` match instead of current-workflow-only aliases.
