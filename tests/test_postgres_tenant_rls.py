import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RLS_MIGRATION = REPO_ROOT / "sql" / "20260412_tenant_row_level_security.sql"
MIGRATION_HELPER = REPO_ROOT / "scripts" / "apply-memory-audit-migration.sh"

WORKFLOW_QUERIES = {
    "n8n/workflows/01_memory_ingest.json": ("Insert Vector", "$1", "\nFROM tenant_context\nON CONFLICT"),
    "n8n/workflows/01_memory_ingest_v3_cached.json": ("Check Cache", "$1", "\nCROSS JOIN tenant_context\n"),
    "n8n/workflows/02_vector_search.json": ("Search Vectors", "$2", "\nCROSS JOIN tenant_context\n"),
    "n8n/workflows/04_executor_dispatch.json": ("Insert Episode", "$1", "\nFROM tenant_context;"),
    "n8n/workflows-v3/01_memory_ingest.json": ("Insert Vector", "$1", "\nFROM tenant_context\nON CONFLICT"),
    "n8n/workflows-v3/02_vector_search.json": ("Search Vectors", "$2", "\nCROSS JOIN tenant_context\n"),
    "n8n/workflows-v3/04_executor_dispatch.json": ("Insert Episode", "$1", "\nFROM tenant_context;"),
}


class PostgresTenantRlsTests(unittest.TestCase):
    maxDiff = None

    def test_migration_helper_applies_rls_migration(self) -> None:
        helper = MIGRATION_HELPER.read_text(encoding="utf-8")

        self.assertIn(
            "20260412_tenant_row_level_security.sql",
            helper,
            "memory/audit migration helper must apply the tenant RLS migration",
        )

    def test_rls_migration_enables_and_forces_tenant_isolation(self) -> None:
        sql = RLS_MIGRATION.read_text(encoding="utf-8")

        self.assertIn(
            "CREATE TABLE IF NOT EXISTS memory_episodes",
            sql,
            "memory_episodes must be managed by schema migration before RLS can protect it",
        )

        for table_name in ("memory_vectors", "memory_episodes"):
            self.assertRegex(
                sql,
                re.compile(
                    rf"ALTER TABLE {table_name}\s+ENABLE ROW LEVEL SECURITY;",
                    re.IGNORECASE,
                ),
            )
            self.assertRegex(
                sql,
                re.compile(
                    rf"ALTER TABLE {table_name}\s+FORCE ROW LEVEL SECURITY;",
                    re.IGNORECASE,
                ),
            )
            self.assertRegex(
                sql,
                re.compile(
                    rf"CREATE POLICY .* ON {table_name}.*USING\s*\(\s*tenant_id\s*=\s*app_current_tenant_id\(\)\s*\)",
                    re.IGNORECASE | re.DOTALL,
                ),
            )
            self.assertRegex(
                sql,
                re.compile(
                    rf"CREATE POLICY .* ON {table_name}.*WITH CHECK\s*\(\s*tenant_id\s*=\s*app_current_tenant_id\(\)\s*\)",
                    re.IGNORECASE | re.DOTALL,
                ),
            )

    def test_workflow_queries_set_tenant_context_before_touching_rls_tables(self) -> None:
        for relative_path, (node_name, tenant_param, tenant_context_reference) in WORKFLOW_QUERIES.items():
            workflow = json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
            query = next(
                node["parameters"]["query"]
                for node in workflow["nodes"]
                if node["name"] == node_name
            )

            expected_snippet = (
                f"WITH tenant_context AS (SELECT set_config('app.current_tenant_id', {tenant_param}, true) AS tenant_ctx)"
            )
            self.assertIn(
                expected_snippet,
                query,
                f"{relative_path}:{node_name} must set app.current_tenant_id in the same statement",
            )
            self.assertIn(
                tenant_context_reference,
                query,
                f"{relative_path}:{node_name} must reference tenant_context so PostgreSQL executes set_config()",
            )


if __name__ == "__main__":
    unittest.main()
