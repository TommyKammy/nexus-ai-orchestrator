from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
QUALITY_GATES_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "quality-gates.yml"
CODEOWNERS = REPO_ROOT / ".github" / "CODEOWNERS"
BRANCH_PROTECTION_RUNBOOK = REPO_ROOT / "docs" / "branch-protection-checks-runbook.md"
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
PR_TEMPLATE = REPO_ROOT / ".github" / "pull_request_template.md"


class GovernanceDefaultsTests(unittest.TestCase):
    def test_quality_gates_uses_regression_entrypoint(self):
        workflow = QUALITY_GATES_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("bash scripts/ci/regression.sh", workflow)

    def test_codeowners_covers_critical_governance_paths(self):
        codeowners = CODEOWNERS.read_text(encoding="utf-8")

        for entry in (
            "/.github/CODEOWNERS",
            "/.github/workflows/",
            "/scripts/ci/",
            "/policy/",
            "/SECURITY.md",
            "/n8n/workflows-v3/05_policy_approval.json",
        ):
            self.assertIn(entry, codeowners)

    def test_branch_protection_runbook_documents_multi_person_reviews(self):
        runbook = BRANCH_PROTECTION_RUNBOOK.read_text(encoding="utf-8")

        self.assertIn("required_approving_review_count: 2", runbook)
        self.assertIn("require_code_owner_reviews: true", runbook)

    def test_contributing_and_pr_template_match_governance_defaults(self):
        contributing = CONTRIBUTING.read_text(encoding="utf-8")
        pr_template = PR_TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("bash scripts/ci/regression.sh", contributing)
        self.assertIn("two human approvals", pr_template)


if __name__ == "__main__":
    unittest.main()
