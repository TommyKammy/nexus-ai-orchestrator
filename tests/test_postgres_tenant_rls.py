import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RLS_MIGRATION = REPO_ROOT / "sql" / "20260412_tenant_row_level_security.sql"
MIGRATION_HELPER = REPO_ROOT / "scripts" / "apply-memory-audit-migration.sh"

LEGACY_WORKFLOW_QUERIES = {
    "n8n/workflows/01_memory_ingest.json": ("Insert Vector", "$1", "\nFROM tenant_context\nON CONFLICT"),
    "n8n/workflows/01_memory_ingest_v3_cached.json": ("Check Cache", "$1", "\nCROSS JOIN tenant_context\n"),
    "n8n/workflows/02_vector_search.json": ("Search Vectors", "$2", "\nCROSS JOIN tenant_context\n"),
    "n8n/workflows/04_executor_dispatch.json": ("Insert Episode", "$1", "\nFROM tenant_context;"),
}

SERVICE_BOUNDARY_WORKFLOWS = {
    "n8n/workflows-v3/01_memory_ingest.json": {
        "node_name": "Insert Vector",
        "url": "http://policy-bundle-server:8088/internal/tenant-data/memory/vector",
        "tenant_header_reference": "={{ $input.first().json.tenant_id }}",
        "json_body_snippets": (
            "tenant_id: $input.first().json.tenant_id",
            "scope: $input.first().json.scope",
            "embedding: $input.first().json.embedding",
        ),
    },
    "n8n/workflows-v3/02_vector_search.json": {
        "node_name": "Search Vectors",
        "url": "http://policy-bundle-server:8088/internal/tenant-data/memory/search",
        "tenant_header_reference": "={{ $input.first().json.tenant_id }}",
        "json_body_snippets": (
            "tenant_id: $input.first().json.tenant_id",
            "scope: $input.first().json.scope",
            "embedding: $input.first().json.embedding",
        ),
    },
    "n8n/workflows-v3/04_executor_dispatch.json": {
        "node_name": "Insert Episode",
        "url": "http://policy-bundle-server:8088/internal/tenant-data/memory/episode",
        "tenant_header_reference": "={{ $('Finalize Success Payload').first().json.tenant_id }}",
        "json_body_snippets": (
            "tenant_id: $('Finalize Success Payload').first().json.tenant_id",
            "scope: $('Finalize Success Payload').first().json.scope",
            "metadata_jsonb: $('Finalize Success Payload').first().json.output || {}",
        ),
    },
}


class PostgresTenantRlsTests(unittest.TestCase):
    maxDiff = None

    def _load_workflow_node(self, relative_path: str, node_name: str) -> dict:
        workflow = json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
        return next(node for node in workflow["nodes"] if node["name"] == node_name)

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

    def test_legacy_workflow_queries_set_tenant_context_before_touching_rls_tables(self) -> None:
        for relative_path, (node_name, tenant_param, tenant_context_reference) in LEGACY_WORKFLOW_QUERIES.items():
            query = self._load_workflow_node(relative_path, node_name)["parameters"]["query"]

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

    def test_migrated_workflows_use_internal_tenant_service_boundary_for_rls_tables(self) -> None:
        for relative_path, expectations in SERVICE_BOUNDARY_WORKFLOWS.items():
            node_name = expectations["node_name"]
            node = self._load_workflow_node(relative_path, node_name)
            parameters = node["parameters"]
            headers = {
                header["name"]: header["value"]
                for header in parameters.get("headerParameters", {}).get("parameters", [])
            }

            self.assertEqual(
                node["type"],
                "n8n-nodes-base.httpRequest",
                f"{relative_path}:{node_name} must route RLS-protected data through an internal HTTP service boundary",
            )
            self.assertEqual(
                parameters.get("url"),
                expectations["url"],
                f"{relative_path}:{node_name} must target the tenant-data service boundary",
            )
            self.assertEqual(
                headers.get("X-API-Key"),
                "={{ $env.POLICY_BUNDLE_INTERNAL_API_KEY || $env.N8N_WEBHOOK_API_KEY }}",
                f"{relative_path}:{node_name} must authenticate its internal tenant-data call",
            )
            self.assertEqual(
                headers.get("X-Authenticated-Tenant-Id"),
                expectations["tenant_header_reference"],
                f"{relative_path}:{node_name} must forward the authenticated tenant identity",
            )

            json_body = parameters.get("jsonBody", "")
            for snippet in expectations["json_body_snippets"]:
                self.assertIn(
                    snippet,
                    json_body,
                    f"{relative_path}:{node_name} must include tenant-aware payload fields for the service boundary",
                )


if __name__ == "__main__":
    unittest.main()
