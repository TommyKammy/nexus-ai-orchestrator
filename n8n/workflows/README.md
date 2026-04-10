# n8n Workflows for AI Orchestrator

This directory contains 4 workflow JSON files for the AI orchestration system.

## Shared Webhook Authentication

All non-Slack n8n webhook entry points are expected to enforce the same auth contract before any workflow side effects run.

- Required secret: `N8N_WEBHOOK_API_KEY`
- Accepted request headers: `X-API-Key: <key>` or `Authorization: Bearer <key>`
- Failure behavior: invalid or missing credentials return `401 Unauthorized`

Examples in this document use `X-API-Key` so they stay aligned with the default Caddy policy.

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

**Output:** Data stored in `memory_facts`, `memory_vectors`, and `audit_events` tables

---

### 02_vector_search.json
**Purpose:** Retrieve top-k memories for a scope (ILIKE fallback until embeddings)

**Webhook Path:** `POST /webhook/memory/search`

**Input:**
```json
{
  "scope": "user:123",
  "query": "PDF",
  "k": 5
}
```

**Behavior:** Performs case-insensitive search on memory_vectors.content

**Output:** Search results stored in execution data; audit event logged

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
  "payload": {"optional": "data"}
}
```

**Validation:**
- Required: `actor`, `action`, `target`, `decision`
- Decision must be: `allowed`, `denied`, or `requires_approval`
- `payload.request_id`, `payload.policy_id`, `payload.policy_version` are required

**Output:** Record stored in `audit_events` table with `payload_jsonb`

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
- Proceeds to execution flow and stores episode/audit records when policy allows

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
  "policy_version": "2026-02-20"
}
```

**Output:** Approval decision appended to `audit_events`

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
  -d '{"scope":"user:123","query":"PDF","k":5}'
```
**Result:** ✓ Query executed and audit event logged

### Test 3: Audit Append
```bash
curl -X POST 'https://n8n-s-app01.tmcast.net/webhook/audit/append' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: YOUR_WEBHOOK_KEY' \
  -d '{"actor":"test:user","action":"test_action","target":"user:123","decision":"allowed","payload":{"test":true}}'
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
