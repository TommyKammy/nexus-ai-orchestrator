# Issue #127: Harden governance defaults for CI, CODEOWNERS, and policy change approval

## Supervisor Snapshot
- Issue URL: https://github.com/TommyKammy/nexus-ai-orchestrator/issues/127
- Branch: codex/issue-127
- Workspace: .
- Journal: .codex-supervisor/issues/127/issue-journal.md
- Current phase: reproducing
- Attempt count: 1 (implementation=1, repair=0)
- Last head SHA: 932d52a6cd6d6bba326e5fd99f33124d39e319a2
- Blocked reason: none
- Last failure signature: none
- Repeated failure signature count: 0
- Updated at: 2026-04-13T12:51:53.321Z

## Latest Codex Summary
- None yet.

## Active Failure Context
- None recorded.

## Codex Working Notes
### Current Handoff
- Hypothesis: Governance defaults were too weak in three concrete places: `quality-gates` bypassed the repo regression entrypoint, `CODEOWNERS` did not explicitly cover governance-critical paths, and contributor/runbook docs did not encode a two-human-approval expectation for sensitive policy/CI changes.
- What changed: Added `tests/test_governance_defaults.py` to lock the contract; updated `.github/workflows/quality-gates.yml` to run `bash scripts/ci/regression.sh`; expanded `.github/CODEOWNERS` with explicit governance-sensitive paths; aligned `CONTRIBUTING.md`, `.github/pull_request_template.md`, and `docs/branch-protection-checks-runbook.md` around regression verification and two-human approvals with code-owner review on `main`.
- Current blocker: Full local CI-equivalent verification is limited by workstation tooling: `pnpm` is not installed on `PATH`, the Docker CLI only exposes `docker-compose` rather than `docker compose`, and the Docker daemon is unavailable at the configured Colima socket. Draft PR is open at `https://github.com/TommyKammy/nexus-ai-orchestrator/pull/129`.
- Next exact step: Wait for GitHub PR checks/review on PR #129 and manually confirm the `main` branch protection review settings (`required_approving_review_count: 2`, `require_code_owner_reviews: true`, `dismiss_stale_reviews: true`) match the updated runbook.
- Verification gap: `python3 -m unittest -v tests.test_governance_defaults`, `python3 -m unittest -v tests.test_branch_protection_check_names`, and `bash scripts/ci/branch_protection_check_names_check.sh` pass. `bash scripts/ci/build.sh` fails in this environment because `docker compose` is unavailable; `bash scripts/ci/regression.sh` reaches the lint gate with a temporary `pnpm` shim but then fails because Docker daemon access is unavailable.
- Files touched: `.github/workflows/quality-gates.yml`, `.github/CODEOWNERS`, `docs/branch-protection-checks-runbook.md`, `CONTRIBUTING.md`, `.github/pull_request_template.md`, `tests/test_governance_defaults.py`.
- Rollback concern: Low. Changes are limited to CI/workflow/docs ownership metadata and a focused contract test; rollback is a straight revert if the stricter governance defaults need to be relaxed.
- Last focused command: `gh pr create --draft --base main --head codex/issue-127 --title "Harden governance defaults for CI and review policy" --body-file -`
### Scratchpad
- Keep this section short. The supervisor may compact older notes automatically.
