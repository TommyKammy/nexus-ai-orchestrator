from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
QUALITY_GATES_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "quality-gates.yml"
CODEOWNERS = REPO_ROOT / ".github" / "CODEOWNERS"
BRANCH_PROTECTION_RUNBOOK = REPO_ROOT / "docs" / "branch-protection-checks-runbook.md"
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
PR_TEMPLATE = REPO_ROOT / ".github" / "pull_request_template.md"


class GovernanceDefaultsTests(unittest.TestCase):
    def _codeowners_owners_for(self, repo_path: str) -> list[str]:
        owners: list[str] = []
        normalized_path = repo_path.lstrip("/")

        for raw_line in CODEOWNERS.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            pattern, *line_owners = line.split()
            normalized_pattern = pattern.lstrip("/")

            if pattern == "*":
                owners = line_owners
                continue

            if normalized_pattern.endswith("/"):
                prefix = normalized_pattern.rstrip("/")
                if normalized_path == prefix or normalized_path.startswith(f"{prefix}/"):
                    owners = line_owners
                continue

            if normalized_pattern.endswith("/**"):
                prefix = normalized_pattern[:-3].rstrip("/")
                if normalized_path == prefix or normalized_path.startswith(f"{prefix}/"):
                    owners = line_owners
                continue

            if normalized_path == normalized_pattern:
                owners = line_owners

        return owners

    def test_quality_gates_uses_regression_entrypoint(self):
        workflow = QUALITY_GATES_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("bash scripts/ci/regression.sh", workflow)

    def test_codeowners_covers_critical_governance_paths(self):
        critical_paths = (
            ".github/CODEOWNERS",
            ".github/workflows/quality-gates.yml",
            "scripts/ci/regression.sh",
            "policy/opa/risk.rego",
            "SECURITY.md",
            "n8n/workflows-v3/05_policy_approval.json",
        )

        for repo_path in critical_paths:
            owners = self._codeowners_owners_for(repo_path)
            self.assertTrue(owners, f"missing CODEOWNERS coverage for {repo_path}")
            self.assertGreaterEqual(
                len(owners),
                2,
                f"expected multiple owners for {repo_path}, found {owners}",
            )

    def test_branch_protection_runbook_documents_multi_person_reviews(self):
        runbook = BRANCH_PROTECTION_RUNBOOK.read_text(encoding="utf-8")

        self.assertIn("required_approving_review_count: 2", runbook)
        self.assertIn("require_code_owner_reviews: true", runbook)

    def test_contributing_and_pr_template_match_governance_defaults(self):
        contributing = CONTRIBUTING.read_text(encoding="utf-8")
        pr_template = PR_TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("bash scripts/ci/regression.sh", contributing)
        self.assertIn("bash scripts/ci/regression.sh", pr_template)
        self.assertIn("two human approvals", contributing)
        self.assertIn("two human approvals", pr_template)


if __name__ == "__main__":
    unittest.main()
