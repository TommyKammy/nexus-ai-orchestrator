import http.client
import json
import logging
import os
import subprocess
import sys
import threading
from http.server import HTTPServer
from pathlib import Path
from typing import Optional
from unittest.mock import Mock, patch

import pytest

from executor.api_server import ExecutorHandler
from executor.api_server import start_server


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


def _post_json_raw(port: int, path: str, payload: dict, headers: Optional[dict] = None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    conn.request("POST", path, body=json.dumps(payload), headers=request_headers)
    response = conn.getresponse()
    body = response.read().decode("utf-8")
    response_headers = dict(response.getheaders())
    conn.close()
    return response.status, json.loads(body), response_headers


def _post_json(port: int, path: str, payload: dict):
    status, parsed, _headers = _post_json_raw(port, path, payload)
    return status, parsed


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


def _options(port: int, path: str, headers: Optional[dict] = None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("OPTIONS", path, headers=headers or {})
    response = conn.getresponse()
    response.read()
    response_headers = dict(response.getheaders())
    status = response.status
    conn.close()
    return status, response_headers


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


def test_start_server_requires_executor_api_key():
    with patch.dict(os.environ, {}, clear=False), patch(
        "executor.api_server.API_KEY", None
    ), patch("executor.api_server.HTTPServer") as http_server:
        os.environ.pop("EXECUTOR_API_KEY", None)
        with pytest.raises(RuntimeError, match="EXECUTOR_API_KEY"):
            start_server(host="127.0.0.1", port=0)

    http_server.assert_not_called()


def test_start_server_rejects_invalid_max_request_body_bytes():
    with patch("executor.api_server.API_KEY", "secret-key"), patch.dict(
        os.environ, {"EXECUTOR_MAX_REQUEST_BODY_BYTES": "not-an-int"}, clear=False
    ), patch("executor.api_server.HTTPServer") as http_server:
        with pytest.raises(RuntimeError, match="EXECUTOR_MAX_REQUEST_BODY_BYTES must be an integer"):
            start_server(host="127.0.0.1", port=0)

    http_server.assert_not_called()


def test_import_api_server_does_not_crash_on_invalid_max_request_body_env():
    env = os.environ.copy()
    env["EXECUTOR_MAX_REQUEST_BODY_BYTES"] = "not-an-int"
    repo_root = Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import executor.api_server; print('imported')"],
            capture_output=True,
            cwd=repo_root,
            env=env,
            text=True,
            check=False,
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"Import probe timed out after {exc.timeout} seconds")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "imported"


def test_execute_requires_api_key_header_when_configured():
    with patch.dict(os.environ, {"EXECUTOR_API_KEY": "secret-key"}, clear=False), patch(
        "executor.api_server.API_KEY", "secret-key"
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

    assert status == 401
    assert payload["status"] == "error"
    assert payload["error"] == "Unauthorized"


def test_execute_succeeds_with_api_key_header_when_configured():
    with patch.dict(os.environ, {"EXECUTOR_API_KEY": "secret-key"}, clear=False), patch(
        "executor.api_server.API_KEY", "secret-key"
    ), patch(
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
            status, payload, _headers = _post_json_raw(
                server.server_port,
                "/execute",
                {"tenant_id": "t1", "scope": "analysis", "code": "print('ok')", "language": "python"},
                {"X-API-Key": "secret-key", "X-Authenticated-Tenant-Id": "t1"},
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    assert status == 200
    assert payload["status"] == "success"
    assert payload["tenant_id"] == "t1"
    assert payload["scope"] == "analysis"
    assert payload["result"]["stdout"] == "ok"


def test_execute_uses_authenticated_tenant_when_body_omits_tenant_id():
    with patch.dict(os.environ, {"EXECUTOR_API_KEY": "secret-key"}, clear=False), patch(
        "executor.api_server.API_KEY", "secret-key"
    ), patch(
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
            status, payload, _headers = _post_json_raw(
                server.server_port,
                "/execute",
                {"scope": "analysis", "code": "print('ok')", "language": "python"},
                {
                    "X-API-Key": "secret-key",
                    "X-Authenticated-Tenant-Id": "tenant-from-auth",
                },
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    assert status == 200
    assert payload["status"] == "success"
    assert payload["tenant_id"] == "tenant-from-auth"
    assert payload["scope"] == "analysis"


def test_execute_rejects_request_body_tenant_that_conflicts_with_authenticated_tenant():
    with patch.dict(os.environ, {"EXECUTOR_API_KEY": "secret-key"}, clear=False), patch(
        "executor.api_server.API_KEY", "secret-key"
    ), patch(
        "executor.api_server.policy_client.evaluate"
    ) as evaluate_mock, patch("executor.api_server.policy_client.enforce") as enforce_mock, patch(
        "executor.api_server.CodeSandbox"
    ) as sandbox_cls:
        server, thread = _start_server()
        try:
            status, payload, _headers = _post_json_raw(
                server.server_port,
                "/execute",
                {
                    "tenant_id": "tenant-from-body",
                    "scope": "analysis",
                    "code": "print('ok')",
                    "language": "python",
                },
                {
                    "X-API-Key": "secret-key",
                    "X-Authenticated-Tenant-Id": "tenant-from-auth",
                },
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    assert status == 403
    assert payload["status"] == "error"
    assert "tenant" in payload["error"].lower()
    evaluate_mock.assert_not_called()
    enforce_mock.assert_not_called()
    sandbox_cls.assert_not_called()


def test_execute_rejects_oversized_body_before_sandbox_run():
    oversized_code = "x" * 128
    with patch("executor.api_server.API_KEY", "secret-key"), patch(
        "executor.api_server.MAX_REQUEST_BODY_BYTES", 64, create=True
    ), patch("executor.api_server.policy_client.evaluate") as evaluate_mock, patch(
        "executor.api_server.policy_client.enforce"
    ) as enforce_mock, patch("executor.api_server.CodeSandbox") as sandbox_cls:
        server, thread = _start_server()
        try:
            status, payload, _headers = _post_json_raw(
                server.server_port,
                "/execute",
                {"tenant_id": "t1", "scope": "analysis", "code": oversized_code, "language": "python"},
                {"X-API-Key": "secret-key"},
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    assert status == 413
    assert payload["status"] == "error"
    assert "too large" in payload["error"].lower()
    evaluate_mock.assert_not_called()
    enforce_mock.assert_not_called()
    sandbox_cls.assert_not_called()


def test_execute_rejects_invalid_files_map_before_side_effects():
    with patch("executor.api_server.API_KEY", None), patch(
        "executor.api_server.policy_client.evaluate"
    ) as evaluate_mock, patch("executor.api_server.policy_client.enforce") as enforce_mock, patch(
        "executor.api_server.CodeSandbox"
    ) as sandbox_cls:
        server, thread = _start_server()
        try:
            status, payload = _post_json(
                server.server_port,
                "/execute",
                {
                    "tenant_id": "t1",
                    "scope": "analysis",
                    "code": "print('ok')",
                    "files": {"a.txt": {"nested": 1}},
                },
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    assert status == 400
    assert payload["status"] == "error"
    assert "files" in payload["error"]
    evaluate_mock.assert_not_called()
    enforce_mock.assert_not_called()
    sandbox_cls.assert_not_called()


def test_request_id_is_echoed_in_response_header():
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
            status, payload, headers = _post_json_raw(
                server.server_port,
                "/execute",
                {"tenant_id": "t1", "scope": "analysis", "code": "print('ok')", "language": "python"},
                {"X-Request-ID": "req-123"},
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    assert status == 200
    assert payload["request_id"] == "req-123"
    assert headers["X-Request-ID"] == "req-123"


def test_execute_emits_structured_request_log(caplog):
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
        caplog.set_level(logging.INFO, logger="executor.api_server")
        server, thread = _start_server()
        try:
            status, _payload, _headers = _post_json_raw(
                server.server_port,
                "/execute",
                {"tenant_id": "t1", "scope": "analysis", "code": "print('ok')", "language": "python"},
                {"X-Request-ID": "req-log-1"},
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    assert status == 200
    parsed_logs = []
    for record in caplog.records:
        try:
            parsed_logs.append(json.loads(record.getMessage()))
        except json.JSONDecodeError:
            continue

    access_logs = [entry for entry in parsed_logs if entry.get("event") == "request_complete"]
    assert access_logs, "expected at least one structured access log entry"
    matched = [
        entry
        for entry in access_logs
        if entry.get("request_id") == "req-log-1"
        and entry.get("path") == "/execute"
        and entry.get("status") == 200
        and entry.get("latency_ms") is not None
    ]
    assert matched, "expected structured request log with request_id/path/status/latency_ms"


def test_options_echoes_request_id_header():
    with patch("executor.api_server.API_KEY", "secret-key"), patch(
        "executor.api_server.ALLOWED_ORIGINS", ("https://console.example.com",), create=True
    ):
        server, thread = _start_server()
        try:
            status, headers = _options(
                server.server_port,
                "/execute",
                {"Origin": "https://console.example.com", "X-Request-ID": "opt-req-1"},
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    assert status == 200
    assert headers["X-Request-ID"] == "opt-req-1"
    assert headers["Access-Control-Allow-Origin"] == "https://console.example.com"
    assert (
        headers["Access-Control-Allow-Headers"]
        == "Content-Type, X-API-Key, X-Request-ID, X-Authenticated-Tenant-Id"
    )


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
            "decision": "deny",
            "allow": False,
            "requires_approval": True,
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
    baseline_request_metrics = {
        "total": 0,
        "errors": 0,
        "latency_ms_sum": 0.0,
        "latency_ms_count": 0,
        "methods": {},
        "statuses": {},
    }

    with patch("executor.api_server.API_KEY", None), patch(
        "executor.api_server.template_manager.get_sandbox_kwargs", return_value={}
    ), patch("executor.api_server.POLICY_METRICS", baseline_metrics), patch(
        "executor.api_server.REQUEST_METRICS", baseline_request_metrics
    ), patch(
        "executor.api_server.policy_client.evaluate", side_effect=policy_responses
    ), patch(
        "executor.api_server.policy_client.enforce", side_effect=lambda result: bool(result.get("allow"))
    ), patch(
        "executor.api_server.time.monotonic",
        side_effect=[0.0, 1.0, 1.01, 2.0, 2.5, 2.52, 3.0, 3.5, 3.53, 4.0, 5.0],
    ), patch(
        "executor.api_server.ExecutorHandler._request_latency_ms",
        return_value=0.0,
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
    assert fallback_status == 403
    assert fallback_payload["status"] == "error"
    assert fallback_payload["policy"]["error"] == "opa timeout"

    assert metrics_status == 200
    policy_metrics = metrics_payload["metrics"]["policy"]
    request_metrics = metrics_payload["metrics"]["requests"]
    assert policy_metrics["total"] == 3
    assert policy_metrics["allow"] == 1
    assert policy_metrics["deny"] == 2
    assert policy_metrics["requires_approval"] == 0
    assert policy_metrics["errors"] == 1
    assert policy_metrics["latency_ms_count"] == 3
    assert round(policy_metrics["latency_ms_sum"], 3) == 60.0
    assert request_metrics["total"] == 3
    assert request_metrics["errors"] == 2
    assert request_metrics["methods"]["POST"] == 3
    assert request_metrics["statuses"]["200"] == 1
    assert request_metrics["statuses"]["403"] == 2

    assert prom_status == 200
    assert "executor_policy_eval_total 3" in prom_body
    assert 'executor_policy_decisions_total{decision="allow"} 1' in prom_body
    assert 'executor_policy_decisions_total{decision="deny"} 2' in prom_body
    assert "executor_policy_eval_errors_total 1" in prom_body
    assert "executor_policy_eval_latency_ms_sum 60.000" in prom_body
    assert "executor_policy_eval_latency_ms_count 3" in prom_body
    assert "executor_policy_eval_latency_ms_avg 20.000" in prom_body
    assert "executor_policy_eval_latency_ms_avg " in prom_body
    assert "executor_http_requests_total 3" in prom_body
    assert "executor_http_request_errors_total 2" in prom_body
    assert 'executor_http_requests_by_method_total{method="POST"} 3' in prom_body
    assert 'executor_http_requests_by_status_total{status="200"} 1' in prom_body
    assert 'executor_http_requests_by_status_total{status="403"} 2' in prom_body
