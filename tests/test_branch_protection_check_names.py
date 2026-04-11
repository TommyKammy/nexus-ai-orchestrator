import importlib.util
import json
import shutil
import tempfile
import unittest
from unittest import mock
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "check_branch_protection_check_names.py"
)
SPEC = importlib.util.spec_from_file_location("branch_protection_check_names", MODULE_PATH)
branch_protection_check_names = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(branch_protection_check_names)


class BranchProtectionCheckNamesTests(unittest.TestCase):
    def _write_fixture_repo(self) -> tuple[Path, Path, Path, list[Path]]:
        tmpdir = Path(tempfile.mkdtemp(prefix="branch-protection-checks-"))
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        manifest_path = tmpdir / "branch_protection_required_checks.json"
        workflow_dir = tmpdir / "workflows"
        workflow_dir.mkdir()
        docs_dir = tmpdir / "docs"
        docs_dir.mkdir()
        doc_paths = [docs_dir / "checklist.md", docs_dir / "release.md"]

        manifest_path.write_text(
            json.dumps({"main": ["quality-gates", "validate", "import-test"]}, indent=2) + "\n",
            encoding="utf-8",
        )
        (workflow_dir / "quality-gates.yml").write_text(
            "\n".join(
                [
                    "name: Quality Gates",
                    "",
                    "jobs:",
                    "  quality-gates:",
                    "    runs-on: ubuntu-latest",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (workflow_dir / "validate-workflows.yml").write_text(
            "\n".join(
                [
                    "name: Validate workflows",
                    "",
                    "jobs:",
                    "  validate:",
                    "    runs-on: ubuntu-latest",
                    "  import-test:",
                    "    runs-on: ubuntu-latest",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        for doc_path in doc_paths:
            doc_path.write_text("Checks: `quality-gates`, `validate`, `import-test`\n", encoding="utf-8")

        return tmpdir, manifest_path, workflow_dir, doc_paths

    def test_validation_passes_for_matching_manifest_and_short_check_names(self):
        _, manifest_path, workflow_dir, doc_paths = self._write_fixture_repo()

        errors = branch_protection_check_names.validate_branch_protection_check_names(
            manifest_path=manifest_path,
            workflow_dir=workflow_dir,
            branch="main",
            doc_paths=doc_paths,
        )

        self.assertEqual(errors, [])

    def test_validation_fails_when_required_check_is_missing(self):
        _, manifest_path, workflow_dir, doc_paths = self._write_fixture_repo()
        manifest_path.write_text(
            json.dumps({"main": ["quality-gates", "validate", "missing-check"]}, indent=2) + "\n",
            encoding="utf-8",
        )

        errors = branch_protection_check_names.validate_branch_protection_check_names(
            manifest_path=manifest_path,
            workflow_dir=workflow_dir,
            branch="main",
            doc_paths=doc_paths,
        )

        self.assertTrue(any("missing-check" in error for error in errors))

    def test_validation_fails_for_legacy_workflow_job_display_names_in_docs(self):
        _, manifest_path, workflow_dir, doc_paths = self._write_fixture_repo()
        doc_paths[0].write_text(
            "Checks: `Quality Gates / quality-gates`, `validate`, `import-test`\n",
            encoding="utf-8",
        )

        errors = branch_protection_check_names.validate_branch_protection_check_names(
            manifest_path=manifest_path,
            workflow_dir=workflow_dir,
            branch="main",
            doc_paths=doc_paths,
        )

        self.assertTrue(any("Quality Gates / quality-gates" in error for error in errors))

    def test_validation_fails_for_renamed_workflow_aliases_in_docs(self):
        _, manifest_path, workflow_dir, doc_paths = self._write_fixture_repo()
        (workflow_dir / "validate-workflows.yml").write_text(
            "\n".join(
                [
                    "name: Validate workflows",
                    "",
                    "jobs:",
                    "  validate:",
                    "    runs-on: ubuntu-latest",
                    "  import-test:",
                    "    runs-on: ubuntu-latest",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        doc_paths[0].write_text(
            "Checks: `Old Validate Pipeline / validate`, `import-test`\n",
            encoding="utf-8",
        )

        errors = branch_protection_check_names.validate_branch_protection_check_names(
            manifest_path=manifest_path,
            workflow_dir=workflow_dir,
            branch="main",
            doc_paths=doc_paths,
        )

        self.assertTrue(any("Old Validate Pipeline / validate" in error for error in errors))

    def test_default_docs_include_branch_protection_runbook(self):
        self.assertIn(
            branch_protection_check_names.REPO_ROOT / "docs" / "branch-protection-checks-runbook.md",
            branch_protection_check_names.DEFAULT_DOCS,
        )

    def test_parse_workflow_jobs_handles_inline_comments_and_nonstandard_indentation(self):
        _, _, workflow_dir, _ = self._write_fixture_repo()
        workflow_path = workflow_dir / "commented-jobs.yml"
        workflow_path.write_text(
            "\n".join(
                [
                    "name: Test Workflow",
                    "",
                    "jobs: # important jobs section",
                    "   test-job:",
                    "     name: my-check # canonical name",
                    "     runs-on: ubuntu-latest",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        jobs = branch_protection_check_names.parse_workflow_jobs(workflow_path)

        self.assertEqual(jobs, [("test-job", "my-check")])

    def test_read_workflow_name_ignores_inline_comments(self):
        _, _, workflow_dir, _ = self._write_fixture_repo()
        workflow_path = workflow_dir / "workflow-name-comment.yml"
        workflow_path.write_text(
            "\n".join(
                [
                    'name: "Test Workflow # canonical" # actual inline comment',
                    "",
                    "jobs:",
                    "  test-job:",
                    "    runs-on: ubuntu-latest",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        workflow_name = branch_protection_check_names.read_workflow_name(workflow_path)

        self.assertEqual(workflow_name, "Test Workflow # canonical")

    def test_parse_workflow_jobs_ignores_nested_step_and_with_names(self):
        _, _, workflow_dir, _ = self._write_fixture_repo()
        workflow_path = workflow_dir / "nested-step-names.yml"
        workflow_path.write_text(
            "\n".join(
                [
                    "name: Security Audit",
                    "",
                    "jobs:",
                    "  security-audit:",
                    "    runs-on: ubuntu-latest",
                    "    steps:",
                    "      - name: Upload security artifacts",
                    "        uses: actions/upload-artifact@v4",
                    "        with:",
                    "          name: security-scan-artifacts",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        jobs = branch_protection_check_names.parse_workflow_jobs(workflow_path)

        self.assertEqual(jobs, [("security-audit", "security-audit")])

    def test_legacy_doc_aliases_include_all_producer_workflow_names(self):
        produced_checks = {
            "validate": [
                r"C:\repo\.github\workflows\validate-workflows.yml:validate",
                "/tmp/validate-v2.yml:validate",
            ],
        }

        with mock.patch.object(
            branch_protection_check_names,
            "read_workflow_name",
            side_effect=["Validate workflows", "Validate workflows v2"],
        ) as read_workflow_name:
            aliases = branch_protection_check_names.legacy_doc_aliases_for_required_checks(
                required_checks=["validate"],
                produced_checks=produced_checks,
            )

        self.assertEqual(
            aliases,
            ["Validate workflows / validate", "Validate workflows v2 / validate"],
        )
        self.assertEqual(
            read_workflow_name.call_args_list,
            [
                mock.call(Path(r"C:\repo\.github\workflows\validate-workflows.yml")),
                mock.call(Path("/tmp/validate-v2.yml")),
            ],
        )


if __name__ == "__main__":
    unittest.main()
