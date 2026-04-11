import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ci" / "memory_ingest_workflow_check.sh"


class MemoryIngestWorkflowCheckTests(unittest.TestCase):
    maxDiff = None

    def _make_temp_repo(self) -> Path:
        tmpdir = Path(tempfile.mkdtemp(prefix="memory-ingest-workflow-check-"))
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        (tmpdir / "scripts" / "ci").mkdir(parents=True)
        (tmpdir / "n8n" / "workflows").mkdir(parents=True)
        (tmpdir / "n8n" / "workflows-v3").mkdir(parents=True)
        (tmpdir / "scripts" / "ci" / "memory_ingest_workflow_check.sh").write_text(
            SCRIPT_PATH.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return tmpdir

    def _write_workflow(self, repo_root: Path, relative_path: str, nodes: list[dict]) -> None:
        workflow_path = repo_root / relative_path
        workflow_path.write_text(
            __import__("json").dumps({"nodes": nodes}, indent=2) + "\n",
            encoding="utf-8",
        )

    def _postgres_node(
        self,
        name: str,
        query: str,
        query_replacement: Optional[str] = None,
    ) -> dict:
        node = {
            "name": name,
            "type": "n8n-nodes-base.postgres",
            "parameters": {
                "query": query,
            },
        }
        if query_replacement is not None:
            node["parameters"]["additionalFields"] = {
                "queryReplacement": query_replacement,
            }
        return node

    def _node(self, name: str, node_type: str, parameters: Optional[dict] = None) -> dict:
        return {
            "name": name,
            "type": node_type,
            "parameters": parameters or {},
        }

    def _run_check(self, repo_root: Path) -> subprocess.CompletedProcess[str]:
        bash_path = shutil.which("bash")
        if bash_path is None:
            self.fail("bash executable not found in PATH")
        return subprocess.run(
            [bash_path, "scripts/ci/memory_ingest_workflow_check.sh"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_check_fails_for_interpolated_non_insert_vector_postgres_node(self):
        repo_root = self._make_temp_repo()
        safe_vector_query = textwrap.dedent(
            """
            INSERT INTO memory_vectors (
              tenant_id,
              scope,
              content,
              embedding,
              tags,
              source,
              content_hash,
              metadata_jsonb,
              created_at
            )
            VALUES (
              $1,
              $2,
              $3,
              $4::vector,
              $5::jsonb,
              $6,
              $7,
              $8::jsonb,
              NOW()
            )
            ON CONFLICT (tenant_id, scope, content_hash)
            WHERE content_hash IS NOT NULL
            DO UPDATE SET
              content = EXCLUDED.content,
              embedding = EXCLUDED.embedding,
              tags = EXCLUDED.tags,
              source = EXCLUDED.source,
              metadata_jsonb = EXCLUDED.metadata_jsonb
            RETURNING id, content_hash;
            """
        ).strip()
        safe_vector_replacement = "={{ ['tenant', 'scope', 'text', 'embedding', '[]', 'api', $input.first().json.content_hash, '{}'] }}"

        self._write_workflow(
            repo_root,
            "n8n/workflows/01_memory_ingest.json",
            [
                self._postgres_node("Insert Vector", safe_vector_query, safe_vector_replacement),
                self._postgres_node("Insert Audit", "SELECT 1;"),
            ],
        )
        self._write_workflow(
            repo_root,
            "n8n/workflows-v3/01_memory_ingest.json",
            [
                self._postgres_node("Insert Vector", safe_vector_query, safe_vector_replacement),
                self._postgres_node("Insert Facts", "INSERT INTO memory_facts (subject) VALUES ($1);", "={{ ['value'] }}"),
                self._postgres_node(
                    "Insert Audit",
                    "INSERT INTO audit_events (target) VALUES ('{{ $json.scope }}');",
                ),
            ],
        )
        self._write_workflow(
            repo_root,
            "n8n/workflows/01_memory_ingest_v3_cached.json",
            [
                self._postgres_node("Insert Vector", safe_vector_query, safe_vector_replacement),
                self._postgres_node("Insert Audit", "SELECT 1;"),
            ],
        )

        result = self._run_check(repo_root)

        self.assertNotEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("n8n/workflows-v3/01_memory_ingest.json", result.stderr)
        self.assertIn("Insert Audit", result.stderr)

    def test_check_passes_for_parameterized_runtime_queries_and_constant_sql(self):
        repo_root = self._make_temp_repo()
        safe_vector_query = textwrap.dedent(
            """
            INSERT INTO memory_vectors (
              tenant_id,
              scope,
              content,
              embedding,
              tags,
              source,
              content_hash,
              metadata_jsonb,
              created_at
            )
            VALUES (
              $1,
              $2,
              $3,
              $4::vector,
              $5::jsonb,
              $6,
              $7,
              $8::jsonb,
              NOW()
            )
            ON CONFLICT (tenant_id, scope, content_hash)
            WHERE content_hash IS NOT NULL
            DO UPDATE SET
              content = EXCLUDED.content,
              embedding = EXCLUDED.embedding,
              tags = EXCLUDED.tags,
              source = EXCLUDED.source,
              metadata_jsonb = EXCLUDED.metadata_jsonb
            RETURNING id, content_hash;
            """
        ).strip()
        safe_vector_replacement = "={{ ['tenant', 'scope', 'text', 'embedding', '[]', 'api', $input.first().json.content_hash, '{}'] }}"
        safe_facts_query = (
            "INSERT INTO memory_facts (subject, predicate, object, confidence) "
            "VALUES ($1, $2, $3, $4);"
        )
        safe_audit_query = (
            "INSERT INTO audit_events (actor, action, target, decision, payload_jsonb, created_at) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, NOW());"
        )

        self._write_workflow(
            repo_root,
            "n8n/workflows/01_memory_ingest.json",
            [
                self._postgres_node("Insert Facts", safe_facts_query, "={{ ['s', 'p', 'o', 0.9] }}"),
                self._postgres_node("Insert Vector", safe_vector_query, safe_vector_replacement),
                self._postgres_node("Insert Audit", safe_audit_query, "={{ ['actor', 'action', 'target', 'allow', '{}'] }}"),
                self._postgres_node("Health Check", "SELECT 1;"),
            ],
        )
        self._write_workflow(
            repo_root,
            "n8n/workflows-v3/01_memory_ingest.json",
            [
                self._postgres_node("Insert Facts", safe_facts_query, "={{ ['s', 'p', 'o', 0.9] }}"),
                self._postgres_node("Insert Vector", safe_vector_query, safe_vector_replacement),
                self._postgres_node("Insert Audit", safe_audit_query, "={{ ['actor', 'action', 'target', 'allow', '{}'] }}"),
            ],
        )
        self._write_workflow(
            repo_root,
            "n8n/workflows/01_memory_ingest_v3_cached.json",
            [
                self._postgres_node("Insert Facts", safe_facts_query, "={{ ['s', 'p', 'o', 0.9] }}"),
                self._postgres_node("Insert Vector", safe_vector_query, safe_vector_replacement),
                self._postgres_node("Insert Audit", safe_audit_query, "={{ ['actor', 'action', 'target', 'allow', '{}'] }}"),
                self._postgres_node("Static Bootstrap", "SELECT NOW();"),
            ],
        )

        result = self._run_check(repo_root)

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Memory ingest workflow metadata checks passed.", result.stdout)

    def test_check_fails_when_insert_vector_replacement_mentions_content_hash_without_binding_it(self):
        repo_root = self._make_temp_repo()
        safe_vector_query = textwrap.dedent(
            """
            INSERT INTO memory_vectors (
              tenant_id,
              scope,
              content,
              embedding,
              tags,
              source,
              content_hash,
              metadata_jsonb,
              created_at
            )
            VALUES (
              $1,
              $2,
              $3,
              $4::vector,
              $5::jsonb,
              $6,
              $7,
              $8::jsonb,
              NOW()
            )
            ON CONFLICT (tenant_id, scope, content_hash)
            WHERE content_hash IS NOT NULL
            DO UPDATE SET
              content = EXCLUDED.content,
              embedding = EXCLUDED.embedding,
              tags = EXCLUDED.tags,
              source = EXCLUDED.source,
              metadata_jsonb = EXCLUDED.metadata_jsonb
            RETURNING id, content_hash;
            """
        ).strip()
        loose_vector_replacement = "={{ ['tenant', 'scope', 'text', 'embedding', '[]', 'api', 'hash', '{}'] }}"

        self._write_workflow(
            repo_root,
            "n8n/workflows/01_memory_ingest.json",
            [
                self._postgres_node("Insert Vector", safe_vector_query, loose_vector_replacement),
                self._postgres_node("Insert Audit", "SELECT 1;"),
            ],
        )
        self._write_workflow(
            repo_root,
            "n8n/workflows-v3/01_memory_ingest.json",
            [
                self._postgres_node("Insert Vector", safe_vector_query, loose_vector_replacement),
                self._postgres_node("Insert Audit", "SELECT 1;"),
            ],
        )
        self._write_workflow(
            repo_root,
            "n8n/workflows/01_memory_ingest_v3_cached.json",
            [
                self._postgres_node("Insert Vector", safe_vector_query, loose_vector_replacement),
                self._postgres_node("Insert Audit", "SELECT 1;"),
            ],
        )

        result = self._run_check(repo_root)

        self.assertNotEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn(
            "Insert Vector queryReplacement in n8n/workflows/01_memory_ingest.json must preserve content_hash",
            result.stderr,
        )

    def test_check_fails_when_query_replacement_has_fewer_bindings_than_placeholders(self):
        repo_root = self._make_temp_repo()
        safe_vector_query = textwrap.dedent(
            """
            INSERT INTO memory_vectors (
              tenant_id,
              scope,
              content,
              embedding,
              tags,
              source,
              content_hash,
              metadata_jsonb,
              created_at
            )
            VALUES (
              $1,
              $2,
              $3,
              $4::vector,
              $5::jsonb,
              $6,
              $7,
              $8::jsonb,
              NOW()
            )
            ON CONFLICT (tenant_id, scope, content_hash)
            WHERE content_hash IS NOT NULL
            DO UPDATE SET
              content = EXCLUDED.content,
              embedding = EXCLUDED.embedding,
              tags = EXCLUDED.tags,
              source = EXCLUDED.source,
              metadata_jsonb = EXCLUDED.metadata_jsonb
            RETURNING id, content_hash;
            """
        ).strip()
        safe_vector_replacement = "={{ ['tenant', 'scope', 'text', 'embedding', '[]', 'api', $input.first().json.content_hash, '{}'] }}"

        self._write_workflow(
            repo_root,
            "n8n/workflows/01_memory_ingest.json",
            [
                self._postgres_node("Insert Facts", "INSERT INTO memory_facts (subject, predicate) VALUES ($1, $2);", "={{ ['only-one'] }}"),
                self._postgres_node("Insert Vector", safe_vector_query, safe_vector_replacement),
                self._postgres_node("Insert Audit", "SELECT 1;"),
            ],
        )
        self._write_workflow(
            repo_root,
            "n8n/workflows-v3/01_memory_ingest.json",
            [
                self._postgres_node("Insert Vector", safe_vector_query, safe_vector_replacement),
                self._postgres_node("Insert Audit", "SELECT 1;"),
            ],
        )
        self._write_workflow(
            repo_root,
            "n8n/workflows/01_memory_ingest_v3_cached.json",
            [
                self._postgres_node("Insert Vector", safe_vector_query, safe_vector_replacement),
                self._postgres_node("Insert Audit", "SELECT 1;"),
            ],
        )

        result = self._run_check(repo_root)

        self.assertNotEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn(
            "queryReplacement only provides 1 bindings for 2 positional placeholders in n8n/workflows/01_memory_ingest.json :: Insert Facts",
            result.stderr,
        )

    def test_check_ignores_non_postgres_nodes_named_insert_vector(self):
        repo_root = self._make_temp_repo()
        safe_vector_query = textwrap.dedent(
            """
            INSERT INTO memory_vectors (
              tenant_id,
              scope,
              content,
              embedding,
              tags,
              source,
              content_hash,
              metadata_jsonb,
              created_at
            )
            VALUES (
              $1,
              $2,
              $3,
              $4::vector,
              $5::jsonb,
              $6,
              $7,
              $8::jsonb,
              NOW()
            )
            ON CONFLICT (tenant_id, scope, content_hash)
            WHERE content_hash IS NOT NULL
            DO UPDATE SET
              content = EXCLUDED.content,
              embedding = EXCLUDED.embedding,
              tags = EXCLUDED.tags,
              source = EXCLUDED.source,
              metadata_jsonb = EXCLUDED.metadata_jsonb
            RETURNING id, content_hash;
            """
        ).strip()
        safe_vector_replacement = "={{ ['tenant', 'scope', 'text', 'embedding', '[]', 'api', $input.first().json.content_hash, '{}'] }}"

        self._write_workflow(
            repo_root,
            "n8n/workflows/01_memory_ingest.json",
            [
                self._postgres_node("Insert Vector", safe_vector_query, safe_vector_replacement),
                self._node("Insert Vector", "n8n-nodes-base.code", {"jsCode": "return [{ json: { ignored: true } }];"}),
                self._postgres_node("Insert Audit", "SELECT 1;"),
            ],
        )
        self._write_workflow(
            repo_root,
            "n8n/workflows-v3/01_memory_ingest.json",
            [
                self._postgres_node("Insert Vector", safe_vector_query, safe_vector_replacement),
                self._postgres_node("Insert Audit", "SELECT 1;"),
            ],
        )
        self._write_workflow(
            repo_root,
            "n8n/workflows/01_memory_ingest_v3_cached.json",
            [
                self._postgres_node("Insert Vector", safe_vector_query, safe_vector_replacement),
                self._postgres_node("Insert Audit", "SELECT 1;"),
            ],
        )

        result = self._run_check(repo_root)

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Memory ingest workflow metadata checks passed.", result.stdout)

    def test_check_fails_when_cached_insert_vector_uses_legacy_insert_shape(self):
        repo_root = self._make_temp_repo()
        safe_vector_query = textwrap.dedent(
            """
            INSERT INTO memory_vectors (
              tenant_id,
              scope,
              content,
              embedding,
              tags,
              source,
              content_hash,
              metadata_jsonb,
              created_at
            )
            VALUES (
              $1,
              $2,
              $3,
              $4::vector,
              $5::jsonb,
              $6,
              $7,
              $8::jsonb,
              NOW()
            )
            ON CONFLICT (tenant_id, scope, content_hash)
            WHERE content_hash IS NOT NULL
            DO UPDATE SET
              content = EXCLUDED.content,
              embedding = EXCLUDED.embedding,
              tags = EXCLUDED.tags,
              source = EXCLUDED.source,
              metadata_jsonb = EXCLUDED.metadata_jsonb
            RETURNING id, content_hash;
            """
        ).strip()
        safe_vector_replacement = "={{ ['tenant', 'scope', 'text', 'embedding', '[]', 'api', $input.first().json.content_hash, '{}'] }}"
        legacy_cached_query = textwrap.dedent(
            """
            INSERT INTO memory_vectors (tenant_id, scope, content, embedding, content_hash, created_at)
            VALUES ($1, $2, $3, $4::vector, $5, NOW());
            """
        ).strip()

        self._write_workflow(
            repo_root,
            "n8n/workflows/01_memory_ingest.json",
            [
                self._postgres_node("Insert Vector", safe_vector_query, safe_vector_replacement),
                self._postgres_node("Insert Audit", "SELECT 1;"),
            ],
        )
        self._write_workflow(
            repo_root,
            "n8n/workflows-v3/01_memory_ingest.json",
            [
                self._postgres_node("Insert Vector", safe_vector_query, safe_vector_replacement),
                self._postgres_node("Insert Audit", "SELECT 1;"),
            ],
        )
        self._write_workflow(
            repo_root,
            "n8n/workflows/01_memory_ingest_v3_cached.json",
            [
                self._postgres_node("Insert Vector", legacy_cached_query, "={{ ['tenant', 'scope', 'text', 'embedding', $input.first().json.content_hash] }}"),
                self._postgres_node("Insert Audit", "SELECT 1;"),
            ],
        )

        result = self._run_check(repo_root)

        self.assertNotEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn(
            "Insert Vector in n8n/workflows/01_memory_ingest_v3_cached.json is missing 'metadata_jsonb'",
            result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
