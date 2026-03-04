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


def _get_json(port: int, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    response = conn.getresponse()
    body = response.read().decode("utf-8")
    conn.close()
    return response.status, json.loads(body)


def _get_text(port: int, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    response = conn.getresponse()
    body = response.read().decode("utf-8")
    conn.close()
    return response.status, body


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
    events = []

    def _evaluate_side_effect(_policy_input):
        events.append("evaluate")
        return {
            "decision": "allow",
            "allow": True,
            "requires_approval": False,
            "risk_score": 0,
            "reasons": [],
        }

    class _TrackingSandbox(_FakeSandbox):
        def __init__(self, **kwargs):
            events.append("sandbox_init")

        def __enter__(self):
            events.append("sandbox_enter")
            return super().__enter__()

        def run_code(self, code, language):
            events.append("sandbox_run")
            return super().run_code(code, language)

    evaluate_mock = Mock(side_effect=_evaluate_side_effect)
    with patch("executor.api_server.API_KEY", None), patch(
        "executor.api_server.template_manager.get_sandbox_kwargs", return_value={}
    ), patch("executor.api_server.policy_client.evaluate", evaluate_mock), patch(
        "executor.api_server.policy_client.enforce", return_value=True
    ), patch("executor.api_server.CodeSandbox", _TrackingSandbox):
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
    assert events.index("evaluate") < events.index("sandbox_enter")
    assert events.index("evaluate") < events.index("sandbox_run")


def test_policy_metrics_exposed_for_decisions_errors_and_latency():
    policy_responses = [
        {
            "decision": "allow",
            "allow": True,
            "requires_approval": False,
            "risk_score": 0,
            "reasons": [],
            "error": None,
        },
        {
            "decision": "deny",
            "allow": False,
            "requires_approval": False,
            "risk_score": 90,
            "reasons": ["task_type_not_allowed"],
            "error": None,
        },
        {
            "decision": "allow",
            "allow": True,
            "requires_approval": False,
            "risk_score": 0,
            "reasons": ["policy_unavailable"],
            "error": "opa timeout",
        },
    ]
    baseline_metrics = {
        "total": 0,
        "allow": 0,
        "deny": 0,
        "requires_approval": 0,
        "errors": 0,
        "latency_ms_sum": 0.0,
        "latency_ms_count": 0,
    }

    with patch("executor.api_server.API_KEY", None), patch(
        "executor.api_server.template_manager.get_sandbox_kwargs", return_value={}
    ), patch("executor.api_server.POLICY_METRICS", baseline_metrics), patch(
        "executor.api_server.policy_client.evaluate", side_effect=policy_responses
    ), patch(
        "executor.api_server.policy_client.enforce", side_effect=lambda result: bool(result.get("allow"))
    ), patch(
        "executor.api_server.time.monotonic",
        side_effect=[1.0, 1.01, 2.0, 2.02, 3.0, 3.03],
    ), patch("executor.api_server.CodeSandbox", _FakeSandbox):
        server, thread = _start_server()
        try:
            allow_status, allow_payload = _post_json(
                server.server_port,
                "/execute",
                {"tenant_id": "t1", "scope": "analysis", "code": "print('ok')", "language": "python"},
            )
            deny_status, deny_payload = _post_json(
                server.server_port,
                "/execute",
                {"tenant_id": "t1", "scope": "analysis", "code": "print('blocked')", "language": "python"},
            )
            fallback_status, fallback_payload = _post_json(
                server.server_port,
                "/execute",
                {"tenant_id": "t1", "scope": "analysis", "code": "print('fallback')", "language": "python"},
            )
            metrics_status, metrics_payload = _get_json(server.server_port, "/metrics")
            prom_status, prom_body = _get_text(server.server_port, "/metrics/prometheus")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    assert allow_status == 200
    assert allow_payload["status"] == "success"
    assert deny_status == 403
    assert deny_payload["status"] == "error"
    assert fallback_status == 200
    assert fallback_payload["status"] == "success"
    assert fallback_payload["policy"]["error"] == "opa timeout"

    assert metrics_status == 200
    policy_metrics = metrics_payload["metrics"]["policy"]
    assert policy_metrics["total"] == 3
    assert policy_metrics["allow"] == 2
    assert policy_metrics["deny"] == 1
    assert policy_metrics["requires_approval"] == 0
    assert policy_metrics["errors"] == 1
    assert policy_metrics["latency_ms_count"] == 3
    assert round(policy_metrics["latency_ms_sum"], 3) == 60.0

    assert prom_status == 200
    assert "executor_policy_eval_total 3" in prom_body
    assert 'executor_policy_decisions_total{decision="allow"} 2' in prom_body
    assert 'executor_policy_decisions_total{decision="deny"} 1' in prom_body
    assert "executor_policy_eval_errors_total 1" in prom_body
    assert "executor_policy_eval_latency_ms_sum 60.000" in prom_body
    assert "executor_policy_eval_latency_ms_count 3" in prom_body
    assert "executor_policy_eval_latency_ms_avg 20.000" in prom_body
    assert "executor_policy_eval_latency_ms_avg " in prom_body
