# Branch Protection Required Checks Runbook

This repository treats the exact GitHub-reported check names for `main` as a
repo-local contract. The canonical source is
`scripts/ci/branch_protection_required_checks.json`.

## Canonical `main` Required Checks

- `quality-gates`
- `validate`
- `import-test`
- `policy-and-executor`
- `security-audit`

## GitHub `main` Review Settings

Apply these review settings alongside the required checks above:

- `required_approving_review_count: 2`
- `require_code_owner_reviews: true`
- `dismiss_stale_reviews: true`

Treat changes to `policy/`, `.github/workflows/`, `.github/CODEOWNERS`,
`scripts/ci/`, `SECURITY.md`, and
`n8n/workflows-v3/05_policy_approval.json` as governance-sensitive. Those
changes should not merge without two human approvals after the latest push.
`/.github/CODEOWNERS` assigns those paths to a shared governance owner set,
not a single owner, so code owner review routing remains redundant.

## Verification Command

Run this before changing workflow job IDs, workflow job `name:` values, or
GitHub branch protection settings:

```bash
bash scripts/ci/branch_protection_check_names_check.sh
```

The command fails when:
- a canonical required check is no longer produced by any workflow job under
  `.github/workflows/`
- an operator-facing doc still uses a stale `Workflow / job` display string
  instead of the exact reported check name

## Safe Update Sequence

1. Rename the workflow job ID or job `name:` in `.github/workflows/*.yml`.
2. Update `scripts/ci/branch_protection_required_checks.json` if the exact
   reported check name changed.
3. Update operator docs to use the exact reported check name, not
   `Workflow / job`.
4. Run `bash scripts/ci/branch_protection_check_names_check.sh`.
5. Run the usual CI verification for the affected change set.
6. After the branch is green, update GitHub `main` branch protection to match
   the canonical list and review settings above.

Do not guess required check names from stale docs or historical GitHub UI
screenshots. Use the manifest and validation command as the source of truth.
