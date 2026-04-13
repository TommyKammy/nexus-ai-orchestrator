import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ci" / "policy_approval_workflow_check.sh"


class PolicyApprovalWorkflowCheckTests(unittest.TestCase):
    maxDiff = None

    def _make_temp_repo(self) -> Path:
        tmpdir = Path(tempfile.mkdtemp(prefix="policy-approval-workflow-check-"))
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        (tmpdir / "scripts" / "ci").mkdir(parents=True)
        (tmpdir / "n8n" / "workflows-v3").mkdir(parents=True)
        (tmpdir / "scripts" / "ci" / "policy_approval_workflow_check.sh").write_text(
            SCRIPT_PATH.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return tmpdir

    def _node(self, name: str, node_type: str, parameters: Optional[dict] = None) -> dict:
        return {
            "name": name,
            "type": node_type,
            "parameters": parameters or {},
        }

    def _workflow_nodes(self, *, insert_body: str) -> list[dict]:
        return [
            self._node("Webhook", "n8n-nodes-base.webhook"),
            self._node("Check Webhook Auth", "n8n-nodes-base.code"),
            self._node("Webhook Authorized?", "n8n-nodes-base.if"),
            self._node("Unauthorized Response", "n8n-nodes-base.respondToWebhook"),
            self._node(
                "Validate Approval",
                "n8n-nodes-base.code",
                {
                    "jsCode": (
                        "const approval = { token: 'x' };\n"
                        "const providedToken = approval.token;\n"
                        "timingSafeEqual('a', 'b');\n"
                        "const secret = $env.N8N_ENCRYPTION_KEY;\n"
                        "throw new Error('policy.decision must be requires_approval');\n"
                    )
                },
            ),
            self._node("Prepare Audit", "n8n-nodes-base.code"),
            self._node("Error Response", "n8n-nodes-base.respondToWebhook"),
            self._node(
                "Insert Approval Audit",
                "n8n-nodes-base.httpRequest",
                {
                    "method": "POST",
                    "url": "http://policy-bundle-server:8088/internal/tenant-data/audit/event",
                    "headerParameters": {
                        "parameters": [
                            {
                                "name": "X-API-Key",
                                "value": "={{ $env.POLICY_BUNDLE_INTERNAL_API_KEY || $env.N8N_WEBHOOK_API_KEY }}",
                            }
                        ]
                    },
                    "jsonBody": insert_body,
                },
            ),
            self._node(
                "Success Response",
                "n8n-nodes-base.respondToWebhook",
                {
                    "json": (
                        "{\n"
                        "  \"result\": \"$('Validate Approval').first().json\",\n"
                        "  \"decision:\": true,\n"
                        "  \"approver:\": true,\n"
                        "  \"policy:\": true\n"
                        "}"
                    )
                },
            ),
        ]

    def _write_workflow(self, repo_root: Path, *, insert_body: str) -> None:
        workflow_path = repo_root / "n8n" / "workflows-v3" / "05_policy_approval.json"
        workflow_path.write_text(
            json.dumps({"nodes": self._workflow_nodes(insert_body=insert_body)}, indent=2) + "\n",
            encoding="utf-8",
        )

    def _run_check(self, repo_root: Path) -> subprocess.CompletedProcess[str]:
        bash_path = shutil.which("bash")
        if bash_path is None:
            self.fail("bash executable not found in PATH")
        return subprocess.run(
            [bash_path, "scripts/ci/policy_approval_workflow_check.sh"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_check_passes_when_insert_body_contains_server_required_fields(self) -> None:
        repo_root = self._make_temp_repo()
        self._write_workflow(
            repo_root,
            insert_body=(
                "={{ JSON.stringify({ actor: 'approver:alice', action: 'policy_approval', "
                "target: 'req-123', decision: 'approved', payload_jsonb: {}, request_id: 'req-123', "
                "policy_id: 'policy-1', policy_version: '1', risk_score: 0, approval: {}, policy: {} }) }}"
            ),
        )

        result = self._run_check(repo_root)

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Policy approval workflow checks passed.", result.stdout)

    def test_check_fails_when_insert_body_omits_actor(self) -> None:
        repo_root = self._make_temp_repo()
        self._write_workflow(
            repo_root,
            insert_body=(
                "={{ JSON.stringify({ action: 'policy_approval', target: 'req-123', decision: 'approved', "
                "payload_jsonb: {}, request_id: 'req-123', policy_id: 'policy-1', "
                "policy_version: '1', risk_score: 0, approval: {}, policy: {} }) }}"
            ),
        )

        result = self._run_check(repo_root)

        self.assertNotEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn(
            "Insert Approval Audit request body is missing 'actor' in n8n/workflows-v3/05_policy_approval.json",
            result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
