import importlib.util
import json
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
