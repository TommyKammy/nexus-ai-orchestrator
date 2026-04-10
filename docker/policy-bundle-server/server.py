#!/usr/bin/env python3
import io
import json
import logging
import mimetypes
import os
import tarfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

POLICY_SOURCE_DIR = os.environ.get("POLICY_SOURCE_DIR", "/policy-source")
POLICY_RUNTIME_DIR = os.environ.get("POLICY_RUNTIME_DIR", "/policy-runtime")
RUNTIME_REGISTRY_PATH = os.path.join(POLICY_RUNTIME_DIR, "policy_registry.json")
N8N_INTERNAL_BASE_URL = os.environ.get("N8N_INTERNAL_BASE_URL", "http://n8n:5678")
UI_ROOT = os.path.join(os.path.dirname(__file__), "ui")
HOST = os.environ.get("BUNDLE_SERVER_HOST", "0.0.0.0")
PORT = int(os.environ.get("BUNDLE_SERVER_PORT", "8088"))
PUBLISH_API_KEY = os.environ.get("POLICY_BUNDLE_PUBLISH_API_KEY", "").strip()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("policy_bundle_server")


def _read_text(path, fallback=""):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return fallback


def _read_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def _read_body_json(handler):
    try:
        content_length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        return None, "invalid content-length"

    raw_body = handler.rfile.read(content_length)
    try:
        payload = json.loads(raw_body.decode("utf-8") if raw_body else "{}")
    except Exception:
        return None, "invalid json"
    return payload, None


def _proxy_n8n_json(method, path, body=None, query=None, timeout=20):
    url = f"{N8N_INTERNAL_BASE_URL.rstrip('/')}{path}"
    if query:
        url = f"{url}?{urlencode(query, doseq=True)}"

    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=True).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = Request(url=url, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            try:
                parsed = json.loads(raw) if raw else {}
            except Exception:
                parsed = {"raw": raw}
            return resp.status, parsed
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"error": raw or str(e)}
        return e.code, parsed
    except URLError as e:
        return 502, {"error": f"n8n upstream unreachable: {e.reason}"}
    except Exception as e:
        return 500, {"error": f"proxy failure: {str(e)}"}


def build_bundle_bytes():
    data = _read_json(os.path.join(POLICY_SOURCE_DIR, "data.json"), {"policy": {}})
    data.setdefault("policy", {})
    data.setdefault("policy_registry", {"workflows": []})
    data.setdefault("bundle_meta", {})
    runtime_registry = _read_json(RUNTIME_REGISTRY_PATH, {})
    if isinstance(runtime_registry.get("workflows"), list):
        data["policy_registry"]["workflows"] = runtime_registry["workflows"]
    if runtime_registry.get("revision_id"):
        data["bundle_meta"]["revision_id"] = runtime_registry["revision_id"]
    if runtime_registry.get("published_at"):
        data["bundle_meta"]["published_at"] = runtime_registry["published_at"]
    if runtime_registry.get("actor"):
        data["bundle_meta"]["actor"] = runtime_registry["actor"]
    data["bundle_meta"]["generated_at"] = datetime.now(timezone.utc).isoformat()

    rego_files = [
        "authz.rego",
        "risk.rego",
        "bundle.rego",
    ]

    mem = io.BytesIO()
    with tarfile.open(fileobj=mem, mode="w:gz") as tar:
        for name in rego_files:
            content = _read_text(os.path.join(POLICY_SOURCE_DIR, name), "")
            if not content:
                continue
            blob = content.encode("utf-8")
            info = tarfile.TarInfo(name=f"policy/{name}")
            info.size = len(blob)
            tar.addfile(info, io.BytesIO(blob))

        data_blob = json.dumps(data, ensure_ascii=True, indent=2).encode("utf-8")
        data_info = tarfile.TarInfo(name="data.json")
        data_info.size = len(data_blob)
        tar.addfile(data_info, io.BytesIO(data_blob))

    mem.seek(0)
    return mem.read()


class Handler(BaseHTTPRequestHandler):
    def _log_json(self, level, payload):
        log_fn = getattr(logger, level, logger.info)
        log_fn(json.dumps(payload, sort_keys=True))

    def _publish_log_context(self, status, payload=None, **extra):
        actor = ""
        revision_id = ""
        workflow_count = None
        if isinstance(payload, dict):
            actor = str(payload.get("actor", "")).strip()
            revision_id = str(payload.get("revision_id", "")).strip()
            workflows = payload.get("workflows")
            if isinstance(workflows, list):
                workflow_count = len(workflows)

        event = {
            "event": "policy_publish",
            "method": getattr(self, "command", ""),
            "path": getattr(self, "path", ""),
            "source_ip": self.client_address[0] if getattr(self, "client_address", None) else "",
            "status": status,
        }
        if actor:
            event["actor"] = actor
        if revision_id:
            event["revision_id"] = revision_id
        if workflow_count is not None:
            event["workflow_count"] = workflow_count
        event.update(extra)
        return event

    def _require_publish_auth(self, payload=None):
        if not PUBLISH_API_KEY:
            self._log_json(
                "error",
                self._publish_log_context(
                    503,
                    payload,
                    outcome="rejected",
                    reason="publish_auth_not_configured",
                ),
            )
            self._send_json(503, {"ok": False, "error": "Publish authentication not configured"})
            return False

        auth_header = self.headers.get("X-API-Key", "").strip()
        if auth_header == PUBLISH_API_KEY:
            return True

        self._log_json(
            "warning",
            self._publish_log_context(
                401,
                payload,
                outcome="rejected",
                reason="invalid_api_key",
            ),
        )
        self._send_json(401, {"ok": False, "error": "Unauthorized"})
        return False

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_runtime_publish(self):
        payload, err = _read_body_json(self)
        if err:
            self._send_json(400, {"ok": False, "error": err})
            return

        if not self._require_publish_auth(payload):
            return

        workflows = payload.get("workflows")
        if not isinstance(workflows, list):
            self._send_json(400, {"ok": False, "error": "workflows must be array"})
            return

        runtime_payload = {
            "revision_id": str(payload.get("revision_id", "")).strip() or f"rev-{int(datetime.now(timezone.utc).timestamp())}",
            "actor": str(payload.get("actor", "n8n-ce")),
            "notes": str(payload.get("notes", "")),
            "published_at": datetime.now(timezone.utc).isoformat(),
            "workflows": workflows,
        }

        Path(POLICY_RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
        tmp_path = f"{RUNTIME_REGISTRY_PATH}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(runtime_payload, f, ensure_ascii=True, indent=2)
            f.write("\n")
        os.replace(tmp_path, RUNTIME_REGISTRY_PATH)

        self._log_json(
            "info",
            self._publish_log_context(
                200,
                runtime_payload,
                outcome="applied",
                notes=str(runtime_payload.get("notes", "")),
            ),
        )
        self._send_json(200, {"ok": True, "revision_id": runtime_payload["revision_id"], "count": len(workflows)})

    def _serve_ui_asset(self, path):
        if path == "/policy-ui" or path == "/policy-ui/":
            path = "/policy-ui/index.html"

        rel = path.removeprefix("/policy-ui/")
        safe_path = os.path.normpath(rel)
        if safe_path.startswith(".."):
            self._send_json(400, {"ok": False, "error": "invalid ui path"})
            return

        target = os.path.join(UI_ROOT, safe_path)
        if not os.path.isfile(target):
            self._send_json(404, {"ok": False, "error": "ui file not found"})
            return

        with open(target, "rb") as f:
            body = f.read()
        mime = mimetypes.guess_type(target)[0] or "application/octet-stream"
        self._send_bytes(200, body, mime)

    def _handle_ui_api_get(self, path, query):
        if path == "/policy-ui/api/list":
            status, payload = _proxy_n8n_json("GET", "/webhook/policy/registry/list")
            self._send_json(status, payload)
            return

        if path == "/policy-ui/api/candidates":
            status, payload = _proxy_n8n_json("GET", "/webhook/policy/registry/candidates")
            self._send_json(status, payload)
            return

        if path == "/policy-ui/api/get":
            workflow_id = query.get("workflow_id", [""])[0]
            task_type = query.get("task_type", [""])[0]
            status, payload = _proxy_n8n_json(
                "GET",
                "/webhook/policy/registry/get",
                query={"workflow_id": workflow_id, "task_type": task_type},
            )
            self._send_json(status, payload)
            return

        if path == "/policy-ui/api/current":
            payload = _read_json(RUNTIME_REGISTRY_PATH, {"workflows": []})
            payload.setdefault("workflows", [])
            self._send_json(200, payload)
            return

        self._send_json(404, {"ok": False, "error": "unknown api path"})

    def _handle_ui_api_post(self, path):
        payload, err = _read_body_json(self)
        if err:
            self._send_json(400, {"ok": False, "error": err})
            return

        if path == "/policy-ui/api/upsert":
            status, response = _proxy_n8n_json("POST", "/webhook/policy/registry/upsert", body=payload)
            self._send_json(status, response)
            return

        if path == "/policy-ui/api/publish":
            if not self._require_publish_auth(payload):
                return
            status, response = _proxy_n8n_json("POST", "/webhook/policy/registry/publish", body=payload)
            log_level = "info" if 200 <= status < 400 else "warning"
            self._log_json(
                log_level,
                self._publish_log_context(
                    status,
                    payload,
                    outcome="proxied" if 200 <= status < 400 else "rejected",
                    upstream="n8n",
                    upstream_response_ok=bool(response.get("ok")) if isinstance(response, dict) else False,
                ),
            )
            self._send_json(status, response)
            return

        if path == "/policy-ui/api/delete":
            status, response = _proxy_n8n_json("POST", "/webhook/policy/registry/delete", body=payload)
            self._send_json(status, response)
            return

        self._send_json(404, {"ok": False, "error": "unknown api path"})

    def do_HEAD(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "11")
            self.end_headers()
            return

        if self.path == "/bundles/policy.tar.gz":
            body = build_bundle_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return

        parsed = urlparse(self.path)
        if parsed.path == "/policy-ui" or parsed.path.startswith("/policy-ui/"):
            self.send_response(200)
            self.end_headers()
            return

        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/healthz":
            self._send_json(200, {"ok": True})
            return

        if parsed.path == "/bundles/policy.tar.gz":
            body = build_bundle_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/registry/current":
            payload = _read_json(RUNTIME_REGISTRY_PATH, {"workflows": []})
            if "workflows" not in payload:
                payload["workflows"] = []
            self._send_json(200, payload)
            return

        if parsed.path.startswith("/policy-ui/api/"):
            self._handle_ui_api_get(parsed.path, parse_qs(parsed.query, keep_blank_values=True))
            return

        if parsed.path == "/policy-ui" or parsed.path.startswith("/policy-ui/"):
            self._serve_ui_asset(parsed.path)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/registry/publish":
            self._handle_runtime_publish()
            return

        if parsed.path.startswith("/policy-ui/api/"):
            self._handle_ui_api_post(parsed.path)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    server = HTTPServer((HOST, PORT), Handler)
    server.serve_forever()
