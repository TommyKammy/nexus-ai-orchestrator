#!/usr/bin/env python3
import io
import json
import logging
import mimetypes
import os
import tarfile
from decimal import Decimal
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
AUTHENTICATED_TENANT_HEADER = "X-Authenticated-Tenant-Id"
DB_HOST = os.environ.get("POLICY_REGISTRY_DB_HOST", "postgres")
DB_PORT = int(os.environ.get("POLICY_REGISTRY_DB_PORT", "5432"))
DB_NAME = os.environ.get("POLICY_REGISTRY_DB_NAME", "ai_memory")
DB_USER = os.environ.get("POLICY_REGISTRY_DB_USER", "ai_user")
DB_PASSWORD = os.environ.get("POLICY_REGISTRY_DB_PASSWORD", "").strip()

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


def _normalize_text(value):
    if value is None:
        return ""
    return str(value).strip()


def _payload_tenant_id(payload):
    if not isinstance(payload, dict):
        return ""
    return _normalize_text(payload.get("tenant_id"))


def _audit_payload_tenant_id(payload):
    if not isinstance(payload, dict):
        return ""
    for key in ("payload_jsonb", "payload"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            tenant_id = _normalize_text(nested.get("tenant_id"))
            if tenant_id:
                return tenant_id
    return ""


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _connect_db():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("psycopg is required for internal tenant data endpoints") from exc

    if not DB_PASSWORD:
        raise RuntimeError("POLICY_REGISTRY_DB_PASSWORD must be set for internal tenant data endpoints")

    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        row_factory=dict_row,
    )


def _db_execute(sql, params=None, *, tenant_id=None, expect="all"):
    with _connect_db() as conn:
        with conn.cursor() as cur:
            if tenant_id:
                cur.execute("SELECT set_config('app.current_tenant_id', %s, true)", [_normalize_text(tenant_id)])
            cur.execute(sql, list(params or []))
            if cur.description is None:
                return {"rowcount": cur.rowcount}
            rows = cur.fetchall()

    rows = _json_safe(rows)
    if expect == "one":
        return rows[0] if rows else None
    return rows


def _require_non_empty(payload, *fields):
    missing = [field for field in fields if not _normalize_text(payload.get(field))]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")


def _insert_memory_facts(payload, *, tenant_id=None):
    facts = payload.get("facts")
    if not isinstance(facts, list):
        facts = []

    subjects = [str((fact or {}).get("subject", "")) for fact in facts]
    predicates = [str((fact or {}).get("predicate", "")) for fact in facts]
    objects = [str((fact or {}).get("object", "")) for fact in facts]
    confidences = [
        float((fact or {}).get("confidence", 0) or 0)
        for fact in facts
    ]

    _db_execute(
        """
        INSERT INTO memory_facts (subject, predicate, object, confidence)
        SELECT fact.subject, fact.predicate, fact.object, fact.confidence
        FROM unnest(%s::text[], %s::text[], %s::text[], %s::double precision[]) AS fact(subject, predicate, object, confidence);
        """,
        [subjects, predicates, objects, confidences],
        expect="none",
    )
    return {"inserted_count": len(subjects)}


def _upsert_memory_vector(payload, *, tenant_id=None):
    tenant_value = _normalize_text(tenant_id or payload.get("tenant_id"))
    _require_non_empty(payload, "scope", "text", "embedding", "content_hash")
    if not tenant_value:
        raise ValueError("tenant_id is required")

    return _db_execute(
        """
        INSERT INTO memory_vectors (
          tenant_id,
          scope,
          content,
          embedding,
          tags,
          source,
          content_hash,
          metadata_jsonb,
          created_at
        )
        VALUES (
          %s,
          %s,
          %s,
          %s::vector,
          %s::jsonb,
          %s,
          %s,
          %s::jsonb,
          NOW()
        )
        ON CONFLICT (tenant_id, scope, content_hash)
        WHERE content_hash IS NOT NULL
        DO UPDATE SET
          content = EXCLUDED.content,
          embedding = EXCLUDED.embedding,
          tags = EXCLUDED.tags,
          source = EXCLUDED.source,
          metadata_jsonb = EXCLUDED.metadata_jsonb
        RETURNING id, content_hash;
        """,
        [
            tenant_value,
            _normalize_text(payload.get("scope")),
            str(payload.get("text")),
            str(payload.get("embedding")),
            json.dumps(payload.get("tags") if isinstance(payload.get("tags"), list) else [], ensure_ascii=True),
            _normalize_text(payload.get("source")) or "unknown",
            _normalize_text(payload.get("content_hash")),
            json.dumps(payload.get("metadata_jsonb") if isinstance(payload.get("metadata_jsonb"), dict) else {}, ensure_ascii=True),
        ],
        tenant_id=tenant_value,
        expect="one",
    ) or {}


def _search_memory_vectors(payload, *, tenant_id=None):
    tenant_value = _normalize_text(tenant_id or payload.get("tenant_id"))
    _require_non_empty(payload, "scope", "embedding")
    if not tenant_value:
        raise ValueError("tenant_id is required")

    requested_k = payload.get("k", 5)
    try:
        k_value = int(requested_k)
    except (TypeError, ValueError) as exc:
        raise ValueError("k must be an integer") from exc
    k_value = max(1, min(k_value, 50))

    rows = _db_execute(
        """
        SELECT id, scope, content, tags, source, created_at,
               (embedding <=> %s::vector) AS cosine_distance
        FROM memory_vectors
        WHERE tenant_id = %s AND scope = %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
        """,
        [
            str(payload.get("embedding")),
            tenant_value,
            _normalize_text(payload.get("scope")),
            str(payload.get("embedding")),
            k_value,
        ],
        tenant_id=tenant_value,
    )
    return {"results": rows}


def _insert_memory_episode(payload, *, tenant_id=None):
    tenant_value = _normalize_text(tenant_id or payload.get("tenant_id"))
    _require_non_empty(payload, "scope", "outcome")
    if not tenant_value:
        raise ValueError("tenant_id is required")

    _db_execute(
        """
        INSERT INTO memory_episodes (
          tenant_id,
          scope,
          summary,
          outcome,
          started_at,
          ended_at,
          metadata_jsonb
        )
        VALUES (
          %s,
          %s,
          'executor task executed',
          %s,
          NOW(),
          NOW(),
          %s::jsonb
        );
        """,
        [
            tenant_value,
            _normalize_text(payload.get("scope")),
            _normalize_text(payload.get("outcome")),
            json.dumps(payload.get("metadata_jsonb") if isinstance(payload.get("metadata_jsonb"), dict) else {}, ensure_ascii=True),
        ],
        tenant_id=tenant_value,
        expect="none",
    )
    return {"status": "ok"}


def _append_audit_event(payload, *, tenant_id=None):
    _require_non_empty(payload, "actor", "action", "target", "decision")

    return _db_execute(
        """
        INSERT INTO audit_events (
          actor,
          action,
          target,
          decision,
          payload_jsonb,
          request_id,
          policy_id,
          policy_version,
          policy_reason,
          risk_score,
          created_at
        )
        VALUES (
          %s,
          %s,
          %s,
          %s,
          %s::jsonb,
          %s,
          %s,
          %s,
          %s,
          %s,
          NOW()
        )
        RETURNING id, request_id, created_at;
        """,
        [
            _normalize_text(payload.get("actor")),
            _normalize_text(payload.get("action")),
            _normalize_text(payload.get("target")),
            _normalize_text(payload.get("decision")),
            json.dumps(payload.get("payload_jsonb") if isinstance(payload.get("payload_jsonb"), dict) else {}, ensure_ascii=True),
            payload.get("request_id"),
            payload.get("policy_id"),
            payload.get("policy_version"),
            payload.get("policy_reason"),
            payload.get("risk_score"),
        ],
        tenant_id=tenant_id,
        expect="one",
    ) or {}


def _upsert_policy_workflow(payload, *, tenant_id=None):
    _require_non_empty(payload, "workflow_id", "task_type", "tenant_id", "scope_pattern")

    return _db_execute(
        """
        INSERT INTO policy_workflows (workflow_id, task_type, tenant_id, scope_pattern, constraints_jsonb, enabled)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s)
        ON CONFLICT (workflow_id, task_type, tenant_id, scope_pattern)
        DO UPDATE SET
          constraints_jsonb = EXCLUDED.constraints_jsonb,
          enabled = EXCLUDED.enabled,
          updated_at = NOW()
        RETURNING workflow_id, task_type, tenant_id, scope_pattern, enabled;
        """,
        [
            _normalize_text(payload.get("workflow_id")),
            _normalize_text(payload.get("task_type")),
            _normalize_text(payload.get("tenant_id")),
            _normalize_text(payload.get("scope_pattern")),
            json.dumps(payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {}, ensure_ascii=True),
            bool(payload.get("enabled")),
        ],
        expect="one",
    ) or {}


def _append_policy_publish_log(payload, *, tenant_id=None):
    _require_non_empty(payload, "revision_id", "action", "actor", "result")

    _db_execute(
        """
        INSERT INTO policy_publish_logs (revision_id, action, actor, result, details_jsonb)
        VALUES (%s, %s, %s, %s, %s::jsonb);
        """,
        [
            _normalize_text(payload.get("revision_id")),
            _normalize_text(payload.get("action")),
            _normalize_text(payload.get("actor")),
            _normalize_text(payload.get("result")),
            json.dumps(payload.get("details_jsonb") if isinstance(payload.get("details_jsonb"), dict) else {}, ensure_ascii=True),
        ],
        expect="none",
    )
    return {"status": "ok"}


def _publish_policy_revision(payload, *, tenant_id=None):
    _require_non_empty(payload, "revision_id", "actor")

    return _db_execute(
        """
        WITH payload AS (
          SELECT COALESCE(
            jsonb_agg(
              jsonb_build_object(
                'workflow_id', workflow_id,
                'task_type', task_type,
                'tenant_id', tenant_id,
                'scope_pattern', scope_pattern,
                'constraints', constraints_jsonb,
                'enabled', enabled
              )
            ),
            '[]'::jsonb
          ) AS workflows
          FROM policy_workflows
        ),
        upserted AS (
          INSERT INTO policy_revisions (revision_id, status, payload_jsonb, notes, author, is_active, published_at)
          SELECT
            %s,
            'published',
            jsonb_build_object('workflows', payload.workflows),
            %s,
            %s,
            true,
            NOW()
          FROM payload
          ON CONFLICT (revision_id)
          DO UPDATE SET
            status = 'published',
            payload_jsonb = EXCLUDED.payload_jsonb,
            notes = EXCLUDED.notes,
            author = EXCLUDED.author,
            is_active = true,
            published_at = NOW()
          RETURNING revision_id, payload_jsonb
        ),
        deactivated AS (
          UPDATE policy_revisions
          SET is_active = false
          WHERE revision_id <> %s
          RETURNING revision_id
        )
        SELECT
          upserted.revision_id,
          upserted.payload_jsonb,
          COALESCE((SELECT count(*) FROM deactivated), 0) AS deactivated_count
        FROM upserted;
        """,
        [
            _normalize_text(payload.get("revision_id")),
            _normalize_text(payload.get("notes")),
            _normalize_text(payload.get("actor")),
            _normalize_text(payload.get("revision_id")),
        ],
        expect="one",
    ) or {}


def _load_published_payload(payload, *, tenant_id=None):
    _require_non_empty(payload, "revision_id")
    row = _db_execute(
        """
        SELECT payload_jsonb
        FROM policy_revisions
        WHERE revision_id = %s
        LIMIT 1;
        """,
        [_normalize_text(payload.get("revision_id"))],
        expect="one",
    )
    return row or {"payload_jsonb": {"workflows": []}}


def _list_policy_workflows(payload, *, tenant_id=None):
    rows = _db_execute(
        """
        SELECT workflow_id, task_type, tenant_id, scope_pattern, constraints_jsonb, enabled, updated_at
        FROM policy_workflows
        ORDER BY updated_at DESC
        LIMIT 500;
        """
    )
    return {"items": rows}


def _get_policy_workflow(payload, *, tenant_id=None):
    _require_non_empty(payload, "workflow_id", "task_type")
    row = _db_execute(
        """
        SELECT workflow_id, task_type, tenant_id, scope_pattern, constraints_jsonb, enabled, created_at, updated_at
        FROM policy_workflows
        WHERE workflow_id = %s AND task_type = %s
        ORDER BY updated_at DESC
        LIMIT 1;
        """,
        [
            _normalize_text(payload.get("workflow_id")),
            _normalize_text(payload.get("task_type")),
        ],
        expect="one",
    )
    return {"item": row}


def _get_unregistered_workflow_ids(payload, *, tenant_id=None):
    rows = _db_execute(
        """
        WITH wf AS (
          SELECT DISTINCT name AS workflow_id
          FROM workflow_entity
          WHERE COALESCE(active, true) = true
        ),
        unregistered AS (
          SELECT wf.workflow_id
          FROM wf
          WHERE NOT EXISTS (
            SELECT 1 FROM policy_workflows pw WHERE pw.workflow_id = wf.workflow_id
          )
        )
        SELECT workflow_id
        FROM unregistered
        ORDER BY workflow_id
        LIMIT 300;
        """
    )
    return {"items": rows}


def _get_unregistered_task_types(payload, *, tenant_id=None):
    rows = _db_execute(
        """
        WITH task_raw AS (
          SELECT DISTINCT task_type
          FROM policy_candidate_events
          WHERE task_type IS NOT NULL
        ),
        unregistered AS (
          SELECT tr.task_type
          FROM task_raw tr
          WHERE NOT EXISTS (
            SELECT 1 FROM policy_workflows pw WHERE pw.task_type = tr.task_type
          )
        )
        SELECT task_type
        FROM unregistered
        ORDER BY task_type
        LIMIT 300;
        """
    )
    return {"items": rows}


def _get_policy_task_types(payload, *, tenant_id=None):
    rows = _db_execute(
        """
        SELECT DISTINCT task_type
        FROM policy_workflows
        ORDER BY task_type
        LIMIT 300;
        """
    )
    return {"items": rows}


def _insert_policy_candidate_event(payload, *, tenant_id=None):
    tenant_value = _normalize_text(tenant_id or payload.get("tenant_id"))
    _require_non_empty(payload, "task_type", "scope")
    if not tenant_value:
        raise ValueError("tenant_id is required")

    return _db_execute(
        """
        INSERT INTO policy_candidate_events (task_type, tenant_id, scope, source)
        VALUES (%s, %s, %s, %s)
        RETURNING id, task_type, tenant_id, scope, created_at;
        """,
        [
            _normalize_text(payload.get("task_type")),
            tenant_value,
            _normalize_text(payload.get("scope")),
            _normalize_text(payload.get("source")) or "policy-bundle-server",
        ],
        tenant_id=tenant_value,
        expect="one",
    ) or {}


def _delete_policy_workflow(payload, *, tenant_id=None):
    _require_non_empty(payload, "workflow_id", "task_type", "tenant_id", "scope_pattern")

    result = _db_execute(
        """
        DELETE FROM policy_workflows
        WHERE workflow_id = %s AND task_type = %s AND tenant_id = %s AND scope_pattern = %s;
        """,
        [
            _normalize_text(payload.get("workflow_id")),
            _normalize_text(payload.get("task_type")),
            _normalize_text(payload.get("tenant_id")),
            _normalize_text(payload.get("scope_pattern")),
        ],
        expect="none",
    )
    return {"deleted_count": int(result.get("rowcount", 0))}


INTERNAL_POST_ROUTES = {
    "/internal/tenant-data/memory/facts": {
        "handler": _insert_memory_facts,
        "tenant_extractor": None,
        "tenant_required": False,
    },
    "/internal/tenant-data/memory/vector": {
        "handler": _upsert_memory_vector,
        "tenant_extractor": _payload_tenant_id,
        "tenant_required": True,
    },
    "/internal/tenant-data/memory/search": {
        "handler": _search_memory_vectors,
        "tenant_extractor": _payload_tenant_id,
        "tenant_required": True,
    },
    "/internal/tenant-data/memory/episode": {
        "handler": _insert_memory_episode,
        "tenant_extractor": _payload_tenant_id,
        "tenant_required": True,
    },
    "/internal/tenant-data/audit/event": {
        "handler": _append_audit_event,
        "tenant_extractor": _audit_payload_tenant_id,
        "tenant_required": False,
    },
    "/internal/tenant-data/policy/workflow/upsert": {
        "handler": _upsert_policy_workflow,
        "tenant_extractor": None,
        "tenant_required": False,
    },
    "/internal/tenant-data/policy/publish-log": {
        "handler": _append_policy_publish_log,
        "tenant_extractor": None,
        "tenant_required": False,
    },
    "/internal/tenant-data/policy/revision/publish": {
        "handler": _publish_policy_revision,
        "tenant_extractor": None,
        "tenant_required": False,
    },
    "/internal/tenant-data/policy/revision/payload": {
        "handler": _load_published_payload,
        "tenant_extractor": None,
        "tenant_required": False,
    },
    "/internal/tenant-data/policy/workflow/list": {
        "handler": _list_policy_workflows,
        "tenant_extractor": None,
        "tenant_required": False,
    },
    "/internal/tenant-data/policy/workflow/get": {
        "handler": _get_policy_workflow,
        "tenant_extractor": None,
        "tenant_required": False,
    },
    "/internal/tenant-data/policy/candidates/workflows": {
        "handler": _get_unregistered_workflow_ids,
        "tenant_extractor": None,
        "tenant_required": False,
    },
    "/internal/tenant-data/policy/candidates/tasks/unregistered": {
        "handler": _get_unregistered_task_types,
        "tenant_extractor": None,
        "tenant_required": False,
    },
    "/internal/tenant-data/policy/candidates/tasks/policy": {
        "handler": _get_policy_task_types,
        "tenant_extractor": None,
        "tenant_required": False,
    },
    "/internal/tenant-data/policy/candidate-event": {
        "handler": _insert_policy_candidate_event,
        "tenant_extractor": _payload_tenant_id,
        "tenant_required": True,
    },
    "/internal/tenant-data/policy/workflow/delete": {
        "handler": _delete_policy_workflow,
        "tenant_extractor": None,
        "tenant_required": False,
    },
}


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

    def _resolve_tenant_identity(self, payload, *, tenant_extractor, tenant_required):
        if tenant_extractor is None:
            return None, None

        header_tenant = _normalize_text(self.headers.get(AUTHENTICATED_TENANT_HEADER, ""))
        body_tenant = _normalize_text(tenant_extractor(payload))

        if tenant_required:
            if not header_tenant or not body_tenant:
                return None, {"ok": False, "error": "missing authenticated tenant identity"}
            if header_tenant != body_tenant:
                return None, {"ok": False, "error": "authenticated tenant identity does not match payload tenant_id"}
            return body_tenant, None

        if header_tenant or body_tenant:
            if not header_tenant or not body_tenant:
                return None, {"ok": False, "error": "tenant identity must be supplied in both header and payload"}
            if header_tenant != body_tenant:
                return None, {"ok": False, "error": "authenticated tenant identity does not match payload tenant_id"}
            return body_tenant, None

        return None, None

    def _handle_internal_post(self, path):
        route = INTERNAL_POST_ROUTES.get(path)
        if route is None:
            self._send_json(404, {"ok": False, "error": "unknown internal api path"})
            return

        payload, err = _read_body_json(self)
        if err:
            self._send_json(400, {"ok": False, "error": err})
            return

        tenant_id, tenant_error = self._resolve_tenant_identity(
            payload,
            tenant_extractor=route["tenant_extractor"],
            tenant_required=route["tenant_required"],
        )
        if tenant_error is not None:
            self._send_json(403, tenant_error)
            return

        try:
            response_payload = route["handler"](payload, tenant_id=tenant_id)
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        except RuntimeError as exc:
            self._send_json(503, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:
            self._log_json(
                "error",
                {
                    "event": "internal_tenant_data_error",
                    "path": path,
                    "error": str(exc),
                },
            )
            self._send_json(500, {"ok": False, "error": "internal tenant data operation failed"})
            return

        self._send_json(200, response_payload if response_payload is not None else {"ok": True})

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

        if parsed.path.startswith("/internal/tenant-data/"):
            self._handle_internal_post(parsed.path)
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
