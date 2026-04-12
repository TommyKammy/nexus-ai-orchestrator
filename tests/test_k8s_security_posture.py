import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INGRESS_MANIFEST = REPO_ROOT / "k8s" / "config" / "deployment" / "ingress.yaml"
OPERATOR_MANIFEST = REPO_ROOT / "k8s" / "config" / "deployment" / "operator-deployment.yaml"


class KubernetesSecurityPostureTests(unittest.TestCase):
    def test_executor_ingress_requires_tls(self):
        ingress_manifest = INGRESS_MANIFEST.read_text(encoding="utf-8")

        self.assertRegex(
            ingress_manifest,
            r"(?ms)^spec:\n.*^\s*tls:\n\s*-\s*hosts:\n\s*-\s*executor\.local\n\s*secretName:\s*\S+",
        )

    def test_kubernetes_redis_path_requires_authenticated_tls(self):
        operator_manifest = OPERATOR_MANIFEST.read_text(encoding="utf-8")

        self.assertNotIn(
            'value: "redis://redis.executor-system.svc.cluster.local:6379"',
            operator_manifest,
        )
        self.assertRegex(
            operator_manifest,
            r'value:\s*"rediss://redis\.executor-system\.svc\.cluster\.local:6379/0"',
        )
        self.assertRegex(
            operator_manifest,
            r"secretKeyRef:\n\s+name:\s+redis-auth\n\s+key:\s+password",
        )
        self.assertIn("--tls-port 6379", operator_manifest)
        self.assertIn("--port 0", operator_manifest)
        self.assertIn("--tls-auth-clients yes", operator_manifest)
        self.assertIn("--requirepass \"$REDIS_PASSWORD\"", operator_manifest)
        self.assertRegex(
            operator_manifest,
            r"secretName:\s+redis-tls",
        )


if __name__ == "__main__":
    unittest.main()
