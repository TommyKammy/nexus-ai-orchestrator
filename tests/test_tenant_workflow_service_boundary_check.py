import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "check_tenant_workflow_service_boundary.py"
)
SPEC = importlib.util.spec_from_file_location("tenant_workflow_service_boundary", MODULE_PATH)
tenant_workflow_service_boundary = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(tenant_workflow_service_boundary)


class TenantWorkflowServiceBoundaryTests(unittest.TestCase):
    def _make_temp_repo(self) -> Path:
        tmpdir = Path(tempfile.mkdtemp(prefix="tenant-workflow-boundary-"))
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        (tmpdir / "n8n" / "workflows-v3").mkdir(parents=True)
        return tmpdir

    def _write_workflow(self, repo_root: Path, relative_path: str, nodes: list[dict]) -> None:
        workflow_path = repo_root / relative_path
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text(json.dumps({"name": workflow_path.stem, "nodes": nodes}, indent=2) + "\n", encoding="utf-8")

    def _write_all_target_workflows(self, repo_root: Path, node_factory) -> None:
        for relative_path in tenant_workflow_service_boundary.TARGET_WORKFLOWS:
            self._write_workflow(repo_root, relative_path, node_factory(relative_path))

    def test_validation_passes_when_target_workflows_only_orchestrate_http_calls(self):
        repo_root = self._make_temp_repo()

        self._write_all_target_workflows(
            repo_root,
            lambda _path: [
                {
                    "name": "Call Internal Service",
                    "type": "n8n-nodes-base.httpRequest",
                    "parameters": {"url": "http://executor:8080/internal/example"},
                }
            ],
        )

        errors = tenant_workflow_service_boundary.validate_repo(repo_root)

        self.assertEqual(errors, [])

    def test_validation_fails_when_any_target_workflow_keeps_a_postgres_node(self):
        repo_root = self._make_temp_repo()

        def node_factory(relative_path: str) -> list[dict]:
            if relative_path.endswith("02_vector_search.json"):
                return [
                    {
                        "name": "Search Vectors",
                        "type": "n8n-nodes-base.postgres",
                        "parameters": {"query": "SELECT * FROM memory_vectors WHERE tenant_id = $1;"},
                    }
                ]
            return [
                {
                    "name": "Call Internal Service",
                    "type": "n8n-nodes-base.httpRequest",
                    "parameters": {"url": "http://executor:8080/internal/example"},
                }
            ]

        self._write_all_target_workflows(repo_root, node_factory)

        errors = tenant_workflow_service_boundary.validate_repo(repo_root)

        self.assertEqual(len(errors), 1)
        self.assertIn("02_vector_search.json", errors[0])
        self.assertIn("Search Vectors", errors[0])

    def test_validation_ignores_postgres_nodes_outside_target_workflows(self):
        repo_root = self._make_temp_repo()
        self._write_all_target_workflows(
            repo_root,
            lambda _path: [
                {
                    "name": "Call Internal Service",
                    "type": "n8n-nodes-base.httpRequest",
                    "parameters": {"url": "http://executor:8080/internal/example"},
                }
            ],
        )
        self._write_workflow(
            repo_root,
            "n8n/workflows-v3/unrelated.json",
            [
                {
                    "name": "Legacy SQL",
                    "type": "n8n-nodes-base.postgres",
                    "parameters": {"query": "SELECT 1;"},
                }
            ],
        )

        errors = tenant_workflow_service_boundary.validate_repo(repo_root)

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
