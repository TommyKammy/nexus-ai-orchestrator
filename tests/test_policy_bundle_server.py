import http.client
import importlib.util
import io
import json
import tarfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "docker" / "policy-bundle-server" / "server.py"
)
SPEC = importlib.util.spec_from_file_location("policy_bundle_server", MODULE_PATH)
policy_bundle_server = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(policy_bundle_server)


def _start_server():
    server = HTTPServer(("127.0.0.1", 0), policy_bundle_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _post_json(port, path, payload, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    conn.request("POST", path, body=json.dumps(payload), headers=request_headers)
    response = conn.getresponse()
    body = response.read().decode("utf-8")
    conn.close()
    return response.status, json.loads(body)


def _get_bytes(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    response = conn.getresponse()
    body = response.read()
    headers = dict(response.getheaders())
    conn.close()
    return response.status, body, headers


class PolicyBundleServerTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.tmp_path = Path(self._tempdir.name)
        self.source_dir = self.tmp_path / "policy-source"
        self.runtime_dir = self.tmp_path / "policy-runtime"
        self.source_dir.mkdir()
        self.runtime_dir.mkdir()
        (self.source_dir / "data.json").write_text('{"policy": {}}', encoding="utf-8")
        self.registry_path = self.runtime_dir / "policy_registry.json"

        self.original_source_dir = policy_bundle_server.POLICY_SOURCE_DIR
        self.original_runtime_dir = policy_bundle_server.POLICY_RUNTIME_DIR
        self.original_registry_path = policy_bundle_server.RUNTIME_REGISTRY_PATH
        self.original_publish_api_key = getattr(policy_bundle_server, "PUBLISH_API_KEY", None)

        policy_bundle_server.POLICY_SOURCE_DIR = str(self.source_dir)
        policy_bundle_server.POLICY_RUNTIME_DIR = str(self.runtime_dir)
        policy_bundle_server.RUNTIME_REGISTRY_PATH = str(self.registry_path)

        self.addCleanup(self._restore_module_globals)

    def _restore_module_globals(self):
        policy_bundle_server.POLICY_SOURCE_DIR = self.original_source_dir
        policy_bundle_server.POLICY_RUNTIME_DIR = self.original_runtime_dir
        policy_bundle_server.RUNTIME_REGISTRY_PATH = self.original_registry_path
        if self.original_publish_api_key is None and hasattr(policy_bundle_server, "PUBLISH_API_KEY"):
            delattr(policy_bundle_server, "PUBLISH_API_KEY")
        else:
            policy_bundle_server.PUBLISH_API_KEY = self.original_publish_api_key

    def test_registry_publish_requires_api_key(self):
        policy_bundle_server.PUBLISH_API_KEY = "publish-secret"
        server, thread = _start_server()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)

        status, payload = _post_json(
            server.server_port,
            "/registry/publish",
            {"workflows": [{"workflow_id": "wf-1", "task_type": "analysis"}]},
        )

        self.assertEqual(status, 401)
        self.assertEqual(payload["ok"], False)
        self.assertEqual(payload["error"], "Unauthorized")
        self.assertFalse(self.registry_path.exists())

    def test_registry_publish_with_api_key_updates_runtime_and_bundle_metadata(self):
        policy_bundle_server.PUBLISH_API_KEY = "publish-secret"

        server, thread = _start_server()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)

        with self.assertLogs("policy_bundle_server", level="INFO") as captured_logs:
            status, payload = _post_json(
                server.server_port,
                "/registry/publish",
                {
                    "revision_id": "rev-123",
                    "actor": "operator@example.com",
                    "notes": "rotate policy bundle",
                    "workflows": [{"workflow_id": "wf-1", "task_type": "analysis"}],
                },
                headers={"X-API-Key": "publish-secret"},
            )
            bundle_status, bundle_body, bundle_headers = _get_bytes(
                server.server_port, "/bundles/policy.tar.gz"
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True, "revision_id": "rev-123", "count": 1})

        runtime_payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(runtime_payload["revision_id"], "rev-123")
        self.assertEqual(runtime_payload["actor"], "operator@example.com")
        self.assertEqual(runtime_payload["notes"], "rotate policy bundle")
        self.assertEqual(
            runtime_payload["workflows"],
            [{"workflow_id": "wf-1", "task_type": "analysis"}],
        )

        self.assertEqual(bundle_status, 200)
        self.assertEqual(bundle_headers["Content-Type"], "application/gzip")
        with tarfile.open(fileobj=io.BytesIO(bundle_body), mode="r:gz") as tar:
            bundle_data = json.loads(tar.extractfile("data.json").read().decode("utf-8"))
        self.assertEqual(bundle_data["policy_registry"]["workflows"], runtime_payload["workflows"])
        self.assertEqual(bundle_data["bundle_meta"]["revision_id"], "rev-123")
        self.assertEqual(bundle_data["bundle_meta"]["actor"], "operator@example.com")
        self.assertEqual(bundle_data["bundle_meta"]["published_at"], runtime_payload["published_at"])
        self.assertIn("generated_at", bundle_data["bundle_meta"])

        log_lines = []
        for line in captured_logs.output:
            _, _, message = line.partition(":")
            _, _, payload_text = message.partition(":")
            log_lines.append(json.loads(payload_text))
        publish_logs = [line for line in log_lines if line.get("event") == "policy_publish"]
        self.assertTrue(publish_logs)
        self.assertEqual(publish_logs[-1]["status"], 200)
        self.assertEqual(publish_logs[-1]["actor"], "operator@example.com")

    def test_policy_ui_publish_requires_api_key_before_proxying_upstream(self):
        original_proxy = policy_bundle_server._proxy_n8n_json
        self.addCleanup(setattr, policy_bundle_server, "_proxy_n8n_json", original_proxy)
        policy_bundle_server.PUBLISH_API_KEY = "publish-secret"

        def _unexpected_proxy(*args, **kwargs):
            raise AssertionError("publish proxy should not be called without auth")

        policy_bundle_server._proxy_n8n_json = _unexpected_proxy

        server, thread = _start_server()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)

        status, payload = _post_json(
            server.server_port,
            "/policy-ui/api/publish",
            {"revision_id": "rev-123", "actor": "policy-ui"},
        )

        self.assertEqual(status, 401)
        self.assertEqual(payload["ok"], False)
        self.assertEqual(payload["error"], "Unauthorized")


if __name__ == "__main__":
    unittest.main()
