import http.client
import json
import threading
from http.server import HTTPServer
from unittest.mock import Mock, patch

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


class _FailingSandbox(_FakeSandbox):
    def run_code(self, code, language):
        return {
            "status": "error",
            "exit_code": 1,
            "stdout": "",
            "stderr": "runtime failure",
            "language": language,
        }


class _TimeoutSandbox(_FakeSandbox):
    def run_code(self, code, language):
        return {
            "status": "error",
            "exit_code": -1,
            "stdout": "",
            "stderr": "Execution exceeded timeout (30s)",
            "error": "Execution exceeded timeout (30s)",
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


def test_execute_runtime_failure_returns_error_payload():
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
        "executor.api_server.CodeSandbox", _FailingSandbox
    ):
        server, thread = _start_server()
        try:
            status, payload = _post_json(
                server.server_port,
                "/execute",
                {"tenant_id": "t1", "scope": "analysis", "code": "raise Exception()", "language": "python"},
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    assert status == 200
    assert payload["status"] == "error"
    assert payload["result"]["exit_code"] == 1
    assert "runtime failure" in payload["result"]["stderr"]


def test_execute_timeout_returns_error_payload():
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
        "executor.api_server.CodeSandbox", _TimeoutSandbox
    ):
        server, thread = _start_server()
        try:
            status, payload = _post_json(
                server.server_port,
                "/execute",
                {
                    "tenant_id": "t1",
                    "scope": "analysis",
                    "code": "while True:\n  pass",
                    "language": "python",
                },
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    assert status == 200
    assert payload["status"] == "error"
    assert payload["result"]["exit_code"] == -1
    assert "timeout" in payload["result"]["stderr"].lower()


def test_execute_policy_denied_returns_403():
    with patch("executor.api_server.API_KEY", None), patch(
        "executor.api_server.template_manager.get_sandbox_kwargs", return_value={}
    ), patch(
        "executor.api_server.policy_client.evaluate",
        return_value={
            "decision": "deny",
            "allow": False,
            "requires_approval": False,
            "risk_score": 90,
            "reasons": ["blocked by policy"],
        },
    ), patch("executor.api_server.policy_client.enforce", return_value=False), patch(
        "executor.api_server.CodeSandbox", _FakeSandbox
    ):
        server, thread = _start_server()
        try:
            status, payload = _post_json(
                server.server_port,
                "/execute",
                {"tenant_id": "t1", "scope": "analysis", "code": "print('blocked')", "language": "python"},
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    assert status == 403
    assert payload["status"] == "error"
    assert "Policy denied" in payload["error"]


def test_execute_policy_requires_approval_returns_403():
    with patch("executor.api_server.API_KEY", None), patch(
        "executor.api_server.template_manager.get_sandbox_kwargs", return_value={}
    ), patch(
        "executor.api_server.policy_client.evaluate",
        return_value={
            "decision": "requires_approval",
            "allow": False,
            "requires_approval": True,
            "risk_score": 55,
            "reasons": ["high_risk_requires_approval"],
        },
    ), patch("executor.api_server.policy_client.enforce", return_value=False), patch(
        "executor.api_server.CodeSandbox"
    ) as sandbox_cls:
        server, thread = _start_server()
        try:
            status, payload = _post_json(
                server.server_port,
                "/execute",
                {"tenant_id": "t1", "scope": "analysis", "code": "print('blocked')", "language": "python"},
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    assert status == 403
    assert payload["status"] == "error"
    assert "requires approval" in payload["error"].lower()
    sandbox_cls.assert_not_called()


def test_execute_policy_evaluated_before_sandbox_run():
    evaluate_mock = Mock(
        return_value={
            "decision": "allow",
            "allow": True,
            "requires_approval": False,
            "risk_score": 0,
            "reasons": [],
        }
    )
    with patch("executor.api_server.API_KEY", None), patch(
        "executor.api_server.template_manager.get_sandbox_kwargs", return_value={}
    ), patch("executor.api_server.policy_client.evaluate", evaluate_mock), patch(
        "executor.api_server.policy_client.enforce", return_value=True
    ), patch("executor.api_server.CodeSandbox", _FakeSandbox):
        server, thread = _start_server()
        try:
            status, _payload = _post_json(
                server.server_port,
                "/execute",
                {
                    "tenant_id": "t1",
                    "scope": "analysis",
                    "code": "print('ok')",
                    "language": "python",
                    "task_type": "code_execution",
                },
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    assert status == 200
    evaluate_mock.assert_called_once()
    policy_input = evaluate_mock.call_args.args[0]
    assert policy_input["action"] == "executor.execute"
    assert policy_input["subject"]["tenant_id"] == "t1"
    assert policy_input["resource"]["task_type"] == "code_execution"
