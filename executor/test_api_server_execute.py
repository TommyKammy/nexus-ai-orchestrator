import http.client
import json
import threading
from http.server import HTTPServer
from unittest.mock import patch

from executor.api_server import ExecutorHandler


class _FakeSandbox:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def write_file(self, path, content):
        return True

    def run_code(self, code, language):
        return {
            "status": "success",
            "exit_code": 0,
            "stdout": "ok",
            "stderr": "",
            "language": language,
        }


def _start_server():
    server = HTTPServer(("127.0.0.1", 0), ExecutorHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _post_json(port: int, path: str, payload: dict):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", path, body=json.dumps(payload), headers={"Content-Type": "application/json"})
    response = conn.getresponse()
    body = response.read().decode("utf-8")
    conn.close()
    return response.status, json.loads(body)


def test_execute_returns_structured_output():
    with patch("executor.api_server.API_KEY", None), patch(
        "executor.api_server.template_manager.get_sandbox_kwargs", return_value={}
    ), patch(
        "executor.api_server.policy_client.evaluate",
        return_value={
            "decision": "allow",
            "allow": True,
            "requires_approval": False,
            "risk_score": 0,
            "reasons": [],
        },
    ), patch("executor.api_server.policy_client.enforce", return_value=True), patch(
        "executor.api_server.CodeSandbox", _FakeSandbox
    ):
        server, thread = _start_server()
        try:
            status, payload = _post_json(
                server.server_port,
                "/execute",
                {"tenant_id": "t1", "scope": "analysis", "code": "print('ok')", "language": "python"},
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    assert status == 200
    assert payload["status"] == "success"
    assert payload["tenant_id"] == "t1"
    assert payload["scope"] == "analysis"
    assert "request_id" in payload
    assert "policy" in payload
    assert "result" in payload
    assert payload["result"]["exit_code"] == 0
    assert payload["result"]["stdout"] == "ok"


def test_execute_missing_fields_returns_error():
    with patch("executor.api_server.API_KEY", None):
        server, thread = _start_server()
        try:
            status, payload = _post_json(server.server_port, "/execute", {"tenant_id": "t1"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    assert status == 400
    assert payload["status"] == "error"
    assert "Missing required fields" in payload["error"]
