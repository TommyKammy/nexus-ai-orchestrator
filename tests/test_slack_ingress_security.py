import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CADDYFILE_PATH = REPO_ROOT / "Caddyfile"
WORKFLOW_PATHS = [
    REPO_ROOT / "n8n" / "workflows" / "slack_chat_minimal_v1.json",
    REPO_ROOT / "n8n" / "workflows-v3" / "slack_chat_minimal_v1.json",
]


class SlackIngressSecurityTests(unittest.TestCase):
    def test_caddy_does_not_keep_slack_specific_bypass_or_internal_auth_injection(self):
        caddyfile = CADDYFILE_PATH.read_text(encoding="utf-8")

        self.assertNotIn("X-Internal-Auth", caddyfile)
        self.assertNotIn("SLACK_INTERNAL_AUTH", caddyfile)
        self.assertNotIn("not path /webhook/slack-command /webhook/slack-command/*", caddyfile)
        self.assertIn("reverse_proxy slack-request-verifier:8089", caddyfile)
        self.assertIn("handle_errors {", caddyfile)
        self.assertIn("respond @rate_limited 429", caddyfile)
        self.assertIn("rate_limit {", caddyfile)
        self.assertIn("match {", caddyfile)

    def test_slack_workflows_keep_immediate_ack_and_router_auth(self):
        for workflow_path in WORKFLOW_PATHS:
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            nodes = workflow.get("nodes", [])
            connections = workflow.get("connections", {})

            ack_node = next(
                (
                    node
                    for node in nodes
                    if node.get("name") == "Immediate ACK"
                    and node.get("type") == "n8n-nodes-base.respondToWebhook"
                ),
                None,
            )
            self.assertIsNotNone(ack_node, f"{workflow_path} should keep the immediate ACK node")

            router_node = next(
                (
                    node
                    for node in nodes
                    if node.get("name") == "Call Brain Router"
                    and node.get("type") == "n8n-nodes-base.httpRequest"
                ),
                None,
            )
            self.assertIsNotNone(router_node, f"{workflow_path} should still call the brain router")

            router_headers = (
                router_node.get("parameters", {})
                .get("headerParameters", {})
                .get("parameters", [])
            )
            self.assertTrue(
                any(
                    header.get("name") == "X-API-Key"
                    and "N8N_WEBHOOK_API_KEY" in str(header.get("value", ""))
                    for header in router_headers
                ),
                f"{workflow_path} should send X-API-Key to the internal chat router",
            )

            slack_webhook_edges = connections.get("Slack Webhook", {}).get("main", [])
            self.assertTrue(slack_webhook_edges and slack_webhook_edges[0])
            self.assertEqual(
                slack_webhook_edges[0][0]["node"],
                ack_node["name"],
                f"{workflow_path} should ACK immediately after the webhook trigger",
            )


if __name__ == "__main__":
    unittest.main()
