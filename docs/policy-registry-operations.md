# Policy Registry Operations (Week2 CE)

## Scope
This runbook covers operational steps for policy registry workflows:
- `06_policy_registry_upsert`
- `12_policy_registry_delete`
- `07_policy_registry_publish`
- `10_policy_registry_candidates`
- OPA bundle reflection (no OPA restart)

## Prerequisites
- n8n workflows are imported and published
- `policy_workflows`, `policy_revisions`, `policy_publish_logs` tables exist
- `policy-bundle-server` and `opa` services are healthy
- `policy-bundle-server` has database access configured for its internal tenant data endpoints (`POLICY_REGISTRY_DB_*`)
- Caddy webhook API key is available (`X-API-Key`)
- Policy bundle publish API key is configured on `policy-bundle-server` (`POLICY_BUNDLE_PUBLISH_API_KEY`)
- Baseline policy includes `security_digest_mail` in `policy/opa/data.json`

## Standard Flow

### 1) Upsert policy rule (`06`)
Send POST to `.../webhook/policy/registry/upsert`.

Example payload:
```json
{
  "workflow_id": "daily_it_security_digest_mailer_executor_v1",
  "task_type": "security_digest_mail",
  "tenant_id": "*",
  "scope_pattern": "*",
  "enabled": true,
  "actor": "ops",
  "constraints": {}
}
```

Expected response:
- `status: ok`
- `action: upsert`

### 2) Publish revision (`07`)
Send POST to `.../webhook/policy/registry/publish`.

Example payload:
```json
{
  "revision_id": "rev-20260222-01",
  "actor": "ops",
  "notes": "publish by operations"
}
```

Expected response:
- `status: ok`
- `action: publish`
- `bundle_publish.ok: true`

Note:
- Publish calls use retry/timeout protection (30s timeout, retries enabled).
- OPA reflection remains asynchronous; validate after 10-30 seconds.

### 2a) Runtime bundle publish authentication
Direct runtime registry updates now require the policy bundle publish key in `X-API-Key`.

Example:
```bash
curl -sS -X POST http://127.0.0.1:8088/registry/publish \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: ${POLICY_BUNDLE_PUBLISH_API_KEY}" \
  -d '{
    "revision_id": "rev-20260222-01",
    "actor": "ops",
    "notes": "publish by operations",
    "workflows": [{"workflow_id": "daily_it_security_digest_mailer_executor_v1", "task_type": "security_digest_mail"}]
  }'
```

Expected response:
- `ok: true`
- `revision_id` matches request
- `count` matches published workflow count

Audit log expectations:
- successful and rejected publish attempts emit structured `policy_publish` log entries from `policy-bundle-server`
- log entries include at least request path, status, actor when supplied, and workflow count when available

### 3) Verify runtime registry
Check bundle-server current registry:
- `GET /registry/current`

Expected:
- revision id matches publish request
- workflows list includes target rule

### 4) Verify OPA reflection
OPA polls bundle every 10-30 seconds.
Query policy decision endpoint and confirm expected decision.

## Operational Notes
- Publish is idempotent for same `revision_id`.
- Use unique `revision_id` for traceability.
- Keep `actor` and `notes` meaningful for audit trails.
- Avoid manual file copy deployments (`/tmp -> /opt`). Use git-based host update flow.
- Guarded v3 registry workflows now orchestrate HTTP calls to `policy-bundle-server` for database-owned registry reads/writes; direct `Postgres` nodes are reserved for legacy workflows outside that guard.

## Lightweight UI (Week3-Day1)
- URL: `https://<host>/policy-ui/`
- The UI calls server-side proxy APIs:
  - `GET /policy-ui/api/list`
  - `GET /policy-ui/api/get`
  - `GET /policy-ui/api/candidates`
  - `POST /policy-ui/api/upsert`
  - `POST /policy-ui/api/delete`
  - `POST /policy-ui/api/publish`
  - `GET /policy-ui/api/current`
- Candidate dropdowns (`task_type`, optional `workflow_id`) are sourced from `10_policy_registry_candidates`.
- Publish from the UI now requires the operator to supply `POLICY_BUNDLE_PUBLISH_API_KEY`; the browser sends it as `X-API-Key` only for `POST /policy-ui/api/publish`.
