import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INGRESS_MANIFEST = REPO_ROOT / "k8s" / "config" / "deployment" / "ingress.yaml"
OPERATOR_MANIFEST = REPO_ROOT / "k8s" / "config" / "deployment" / "operator-deployment.yaml"
EXECUTOR_COMPOSE = REPO_ROOT / "docker-compose.executor.yml"


def extract_compose_service_block(compose_text: str, service_name: str) -> str:
    in_services = False
    in_target_service = False
    block_lines = []

    for line in compose_text.splitlines():
        if not in_services:
            if line == "services:":
                in_services = True
            continue

        if not in_target_service:
            if re.match(rf"^  {re.escape(service_name)}:\s*$", line):
                in_target_service = True
                block_lines.append(line)
            continue

        if re.match(r"^[A-Za-z0-9_-]+:\s*$", line) or re.match(
            r"^  [A-Za-z0-9_-]+:\s*$",
            line,
        ):
            break

        block_lines.append(line)

    return "\n".join(block_lines) + ("\n" if block_lines else "")


class KubernetesSecurityPostureTests(unittest.TestCase):
    def test_executor_compose_avoids_privileged_dind(self):
        executor_compose = EXECUTOR_COMPOSE.read_text(encoding="utf-8")
        executor_block = extract_compose_service_block(executor_compose, "executor")

        self.assertTrue(executor_block, "executor service block should exist")

        self.assertNotRegex(
            executor_block,
            r"(?m)^\s*privileged:\s*true\b",
        )
        self.assertRegex(
            executor_block,
            r"(?m)^\s*runtime:\s*sysbox-runc\b",
        )

    def test_executor_ingress_requires_tls(self):
        ingress_manifest = INGRESS_MANIFEST.read_text(encoding="utf-8")

        self.assertRegex(
            ingress_manifest,
            r"(?ms)^spec:\n.*^\s*tls:\n\s*-\s*hosts:\n\s*-\s*executor\.local\n\s*secretName:\s*executor-edge-tls\b",
        )

    def test_kubernetes_redis_path_requires_authenticated_tls(self):
        operator_manifest = OPERATOR_MANIFEST.read_text(encoding="utf-8")

        self.assertNotRegex(
            operator_manifest,
            r"""value:\s*["']?redis://redis\.executor-system\.svc\.cluster\.local(?::6379)?(?:/[^\s"'#]*)?["']?""",
        )
        self.assertRegex(
            operator_manifest,
            r"""value:\s*["']?rediss://redis\.executor-system\.svc\.cluster\.local:6379/0["']?""",
        )
        self.assertRegex(
            operator_manifest,
            r"(?ms)-\s+name:\s+REDIS_PASSWORD\n\s+valueFrom:\n\s+secretKeyRef:\n\s+name:\s+redis-auth\n\s+key:\s+password",
        )
        self.assertIn("--tls-port 6379", operator_manifest)
        self.assertIn("--port 0", operator_manifest)
        self.assertIn("--tls-auth-clients yes", operator_manifest)
        self.assertIn("--requirepass \"$REDIS_PASSWORD\"", operator_manifest)
        self.assertRegex(
            operator_manifest,
            r"secretName:\s+redis-client-tls",
        )
        self.assertRegex(
            operator_manifest,
            r"secretName:\s+redis-server-tls",
        )
        self.assertNotRegex(
            operator_manifest,
            r"secretName:\s+redis-tls\b",
        )
        self.assertIn('os.environ["REDIS_URL"]', operator_manifest)
        self.assertIn('os.environ.get("REDIS_PASSWORD")', operator_manifest)
        self.assertIn(
            'os.environ.get("REDIS_TLS_ENABLED", "").lower() == "true"',
            operator_manifest,
        )
        self.assertIn('os.environ.get("REDIS_TLS_CA_CERT_FILE")', operator_manifest)
        self.assertIn('os.environ.get("REDIS_TLS_CERT_FILE")', operator_manifest)
        self.assertIn('os.environ.get("REDIS_TLS_KEY_FILE")', operator_manifest)
        self.assertIn("await client.ping()", operator_manifest)
        self.assertRegex(
            operator_manifest,
            r"(?ms)readinessProbe:\n\s+exec:\n\s+command:\n\s+- python\n\s+- -c\n\s+- \|",
        )
        readiness_probe = re.search(
            r"(?m)^ {10}readinessProbe:\n(?P<block>(?:^(?: {12,}[^\n]*)?\n)+)",
            operator_manifest,
        )
        self.assertIsNotNone(readiness_probe)
        self.assertRegex(
            readiness_probe.group("block"),
            r"(?m)^ {12}timeoutSeconds:\s+5$",
        )


if __name__ == "__main__":
    unittest.main()
