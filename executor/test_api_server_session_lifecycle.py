import http.client
import json
import threading
from http.server import HTTPServer
from unittest.mock import patch

from executor.api_server import ExecutorHandler
from executor.session import SessionManager


class _FakeSandbox:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.destroyed = False

    def create(self):
        return None

    def destroy(self):
        self.destroyed = True
        return None

    def run_code(self, code, language, files=None):
        return {
            "status": "success",
            "exit_code": 0,
            "stdout": "session-ok",
            "stderr": "",
            "language": language,
        }


class _FakeStateStore:
    def __init__(self):
        self.saved = {}
        self.deleted = []

    def save(self, session_id, payload, ttl):
        self.saved[session_id] = {"payload": payload, "ttl": ttl}

    def delete(self, session_id):
        self.deleted.append(session_id)
        self.saved.pop(session_id, None)


class _FailingStateStore:
    def save(self, session_id, payload, ttl):
        raise RuntimeError("save failed")

    def delete(self, session_id):
        raise RuntimeError("delete failed")


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


def test_session_lifecycle_create_execute_destroy():
    manager = SessionManager(default_ttl=300, max_sessions=5, enable_cleanup_thread=False)
    with patch("executor.api_server.API_KEY", None), patch(
        "executor.api_server.session_manager", manager
    ), patch(
        "executor.session.CodeSandbox", _FakeSandbox
    ), patch(
        "executor.api_server.policy_client.evaluate",
        return_value={
            "decision": "allow",
            "allow": True,
            "requires_approval": False,
            "risk_score": 0,
            "reasons": [],
        },
    ), patch("executor.api_server.policy_client.enforce", return_value=True):
        server, thread = _start_server()
        try:
            create_status, create_payload = _post_json(
                server.server_port,
                "/session/create",
                {"tenant_id": "t1", "scope": "analysis", "template": "default", "ttl": 120},
            )
            session_id = create_payload.get("session_id")

            execute_status, execute_payload = _post_json(
                server.server_port,
                "/session/execute",
                {"session_id": session_id, "code": "print('ok')", "language": "python"},
            )

            destroy_status, destroy_payload = _post_json(
                server.server_port,
                "/session/destroy",
                {"session_id": session_id},
            )

            missing_status, missing_payload = _post_json(
                server.server_port,
                "/session/execute",
                {"session_id": session_id, "code": "print('after destroy')", "language": "python"},
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            manager.stop()

    assert create_status == 200
    assert create_payload["status"] == "success"
    assert session_id
    assert "request_id" in create_payload

    assert execute_status == 200
    assert execute_payload["status"] == "success"
    assert execute_payload["exit_code"] == 0
    assert execute_payload["stdout"] == "session-ok"
    assert "request_id" in execute_payload

    assert destroy_status == 200
    assert destroy_payload["status"] == "success"
    assert "request_id" in destroy_payload

    assert missing_status == 404
    assert missing_payload["status"] == "error"
    assert "not found or expired" in missing_payload["error"].lower()
    assert "request_id" in missing_payload


def test_session_create_policy_denied_returns_403_without_creating_session():
    manager = SessionManager(default_ttl=300, max_sessions=5, enable_cleanup_thread=False)
    try:
        with patch("executor.api_server.API_KEY", None), patch(
            "executor.api_server.session_manager", manager
        ), patch(
            "executor.api_server.policy_client.evaluate",
            return_value={
                "decision": "deny",
                "allow": False,
                "requires_approval": False,
                "risk_score": 90,
                "reasons": ["task_type_not_allowed"],
            },
        ), patch("executor.api_server.policy_client.enforce", return_value=False):
            server, thread = _start_server()
            try:
                status, payload = _post_json(
                    server.server_port,
                    "/session/create",
                    {"tenant_id": "t1", "scope": "analysis", "template": "default", "ttl": 120},
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        assert status == 403
        assert payload["status"] == "error"
        assert "policy denied" in payload["error"].lower()
        assert manager.list_sessions() == []
    finally:
        manager.stop()


def test_session_manager_persists_ttl_state_with_store():
    state_store = _FakeStateStore()
    manager = SessionManager(
        default_ttl=300,
        max_sessions=5,
        enable_cleanup_thread=False,
        state_store=state_store,
    )
    try:
        with patch("executor.session.CodeSandbox", _FakeSandbox):
            session_id = manager.create_session(
                template="default",
                ttl=45,
                metadata={"tenant_id": "t1", "scope": "analysis"},
            )

            assert state_store.saved[session_id]["ttl"] == 45
            assert state_store.saved[session_id]["payload"]["metadata"]["tenant_id"] == "t1"

            session = manager.get_session(session_id)
            assert session is not None
            assert state_store.saved[session_id]["payload"]["use_count"] == 1

            assert manager.destroy_session(session_id) is True
            assert session_id in state_store.deleted
    finally:
        manager.stop()


def test_session_manager_state_store_errors_do_not_break_lifecycle():
    manager = SessionManager(
        default_ttl=300,
        max_sessions=5,
        enable_cleanup_thread=False,
        state_store=_FailingStateStore(),
    )
    try:
        with patch("executor.session.CodeSandbox", _FakeSandbox):
            session_id = manager.create_session(template="default", ttl=60)
            assert manager.get_session(session_id) is not None
            assert manager.destroy_session(session_id) is True
            assert manager.metrics["errors"] >= 2
    finally:
        manager.stop()


def test_session_manager_state_store_none_disables_env_auto_init():
    with patch.dict("os.environ", {"SESSION_STATE_REDIS_URL": "redis://127.0.0.1:6379/0"}):
        manager = SessionManager(
            default_ttl=300,
            max_sessions=5,
            enable_cleanup_thread=False,
            state_store=None,
        )
    try:
        assert manager._state_store is None
    finally:
        manager.stop()
