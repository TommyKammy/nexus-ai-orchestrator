# n8n Workflows for AI Orchestrator

This directory contains 4 workflow JSON files for the AI orchestration system.

## Shared Webhook Authentication

All non-Slack n8n webhook entry points are expected to enforce the same auth contract before any workflow side effects run.

- Required secret: `N8N_WEBHOOK_API_KEY`
- Accepted request headers: `X-API-Key: <key>` or `Authorization: Bearer <key>`
- Failure behavior: invalid or missing credentials return `401 Unauthorized`

Examples in this document use `X-API-Key`, but the edge and workflow auth gates also accept `Authorization: Bearer <key>` for the same shared secret.

## Tenant Data Service Boundary

The guarded tenant-facing workflows under `n8n/workflows-v3/` no longer embed direct `Postgres` nodes for tenant data access.

- Allowed inside guarded n8n workflows: webhook auth, request validation, OPA evaluation, branching, payload shaping, response formatting, and internal HTTP calls to service-owned data endpoints.
- Must stay behind services: tenant-facing reads/writes for memory vectors, audit events, executor episodes, and policy-registry persistence/query paths.
- Tenant-facing internal service calls must forward `X-Authenticated-Tenant-Id` when the payload carries a concrete `tenant_id`; the service rejects missing or conflicting tenant identity on protected paths.
- Legacy workflows under `n8n/workflows/` may still contain direct SQL while migration guardrails remain in place, but new tenant-facing access patterns should follow the v3 service-boundary model.

## Workflows

### 01_memory_ingest.json
**Purpose:** Store structured facts and semantic memories

**Webhook Path:** `POST /webhook/memory/ingest`

**Input:**
```json
{
  "tenant_id": "t1",
  "scope": "user:123",
  "text": "User prefers PDF reports.",
  "facts": [
    {"subject": "user:123", "predicate": "prefers", "object": "PDF", "confidence": 0.9}
  ],
  "tags": ["preference"],
  "source": "explicit"
}
```

**Validation Rules:**
- Required fields: `tenant_id`, `scope`, `text`
- Facts only stored if confidence >= 0.75 OR source == "explicit"
- Rejects content with API keys, bearer tokens, or private keys
- Empty subject/predicate/object fields are rejected

**Output:** Orchestrates internal service writes for `memory_facts`, `memory_vectors`, and `audit_events`

---

### 02_vector_search.json
**Purpose:** Retrieve top-k memories for a scope (ILIKE fallback until embeddings)

**Webhook Path:** `POST /webhook/memory/search`

**Input:**
```json
{
  "tenant_id": "t1",
  "scope": "user:123",
  "query": "PDF",
  "k": 5
}
```

**Behavior:**
- Evaluates policy before embedding lookup, vector search, and audit side effects proceed
- Returns deny / requires-approval responses with policy metadata when access is blocked
- Generates the query embedding, calls the internal memory search service, and appends an audit event only for authorized requests

**Output:** Search results returned with ranking metadata, `request_id`, and policy context

---

### 03_audit_append.json
**Purpose:** Append-only audit event logging

**Webhook Path:** `POST /webhook/audit/append`

**Input:**
```json
{
  "actor": "workflow:memory_ingest",
  "action": "memory_write",
  "target": "user:123",
  "decision": "allowed",
  "payload": {
    "request_id": "req-123",
    "policy_id": "executor-core-v1",
    "policy_version": "2026-02-20",
    "optional": "data"
  }
}
```

**Validation:**
- Required: `actor`, `action`, `target`, `decision`
- Decision must be: `allowed`, `denied`, or `requires_approval`
- `payload.request_id`, `payload.policy_id`, `payload.policy_version` are required

**Behavior:**
- Evaluates policy before writing audit events
- Returns deny / requires-approval responses instead of inserting rows when policy blocks the request
- Persists the audit row only after an `allow` decision

**Output:** Record appended through the internal audit service with policy metadata and `payload_jsonb`

---

### 04_executor_dispatch.json
**Purpose:** Orchestrate policy evaluation + executor dispatch in one webhook path

**Webhook Path:** `POST /webhook/executor/run`

**Input:**
```json
{
  "tenant_id": "t1",
  "scope": "user:123",
  "task": {"type": "ping", "message": "hello"}
}
```

**Behavior:**
- Validates request payload
- Evaluates `executor.execute` policy via OPA
- Returns deny/approval-required responses when policy blocks execution
- Proceeds to execution flow and stores episode/audit records through internal service boundaries when policy allows

**Output:** Structured success/error response with `request_id`, execution output, and policy metadata

---

### 05_policy_approval.json (v3)
**Purpose:** Approve/reject requests that returned `requires_approval`

**Webhook Path:** `POST /webhook/policy/approval`

**Input:**
```json
{
  "request_id": "req-123",
  "decision": "approved",
  "approver": "alice@example.com",
  "comment": "allowed for incident response",
  "policy_id": "executor-core-v1",
  "policy_version": "2026-02-20",
  "policy": {
    "policy_id": "executor-core-v1",
    "policy_version": "2026-02-20",
    "decision": "requires_approval"
  },
  "approval": {
    "endpoint": "/webhook/policy/approval",
    "method": "POST",
    "token": "<opaque signed token from the prior policy response>"
  }
}
```

**Behavior:**
- Requires authenticated ingress
- Requires the prior `requires_approval` policy object and the signed approval metadata emitted by the gated workflow response
- Uses parameterized SQL for the approval audit append side effect

**Output:** Approval decision appended to `audit_events` only when tied to a valid prior policy path

---

## Import Instructions

All workflows have been imported via n8n CLI:

```bash
# Workflows are imported and activated at:
# /opt/ai-orchestrator/n8n/workflows/

# To re-import if needed:
docker exec ai-n8n n8n import:workflow --input=/tmp/01_memory_ingest.json
docker exec ai-n8n n8n publish:workflow --id=<workflow-id>
```

## Testing

All workflows have been tested and are working:

### Test 1: Memory Ingest
```bash
curl -X POST 'https://n8n-s-app01.tmcast.net/webhook/memory/ingest' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: YOUR_WEBHOOK_KEY' \
  -d '{"tenant_id":"t1","scope":"user:123","text":"User prefers PDF reports.","facts":[{"subject":"user:123","predicate":"prefers","object":"PDF","confidence":0.9}],"tags":["preference"],"source":"explicit"}'
```
**Result:** ✓ Data inserted into memory_facts, memory_vectors, audit_events

### Test 2: Vector Search
```bash
curl -X POST 'https://n8n-s-app01.tmcast.net/webhook/memory/search' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: YOUR_WEBHOOK_KEY' \
  -d '{"tenant_id":"t1","scope":"user:123","query":"PDF","k":5}'
```
**Result:** ✓ Query executed and audit event logged

### Test 3: Audit Append
```bash
curl -X POST 'https://n8n-s-app01.tmcast.net/webhook/audit/append' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: YOUR_WEBHOOK_KEY' \
  -d '{"actor":"test:user","action":"test_action","target":"user:123","decision":"allowed","payload":{"request_id":"req-123","policy_id":"executor-core-v1","policy_version":"2026-02-20","test":true}}'
```
**Result:** ✓ Audit event stored with payload_jsonb

### Test 4: Executor Dispatch
```bash
curl -X POST 'https://n8n-s-app01.tmcast.net/webhook/executor/run' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: YOUR_WEBHOOK_KEY' \
  -d '{"tenant_id":"t1","scope":"user:123","task":{"type":"ping","message":"hello"}}'
```
**Result:** ✓ Episode recorded in memory_episodes

---

## Database Schema

The workflows use these tables:

- `memory_vectors` - Semantic memory storage (embedding nullable)
- `memory_facts` - Structured fact storage
- `memory_episodes` - Executor task episodes
- `audit_events` - Append-only audit log with payload_jsonb and policy metadata

Policy quality queries are available at:
- `tools/policy_evaluation.sql`

---

## Security Notes

- All workflows validate inputs before database writes
- Never interpolate request data directly into SQL strings in Postgres nodes; use `$1`, `$2`, ... placeholders with `additionalFields.queryReplacement`
- Secrets patterns are blocked (API keys, tokens, private keys)
- Audit events are append-only
- Postgres credential uses internal Docker network (no SSL needed)
- SSL disabled for internal Postgres connections

---

## Credential Setup

Postgres credential "ai-postgres" has been created with:
- Host: postgres
- Port: 5432
- Database: ai_memory
- User: ai_user
- SSL: disabled

---

## Verification

Current database state:
- memory_facts: 3 records
- memory_vectors: 3 records
- audit_events: 6 records
- memory_episodes: 1 record

All workflows are active and operational.
