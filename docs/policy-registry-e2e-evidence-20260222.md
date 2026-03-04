# Policy Registry E2E Evidence (2026-02-22)

## Scope
Validation for TKT-18 path:
`06 upsert -> 07 publish -> OPA reflect -> 04_executor_dispatch`

## Environment
- Date: 2026-02-22
- n8n: 2.8.3 (self-hosted)
- OPA: 0.68.0
- Registry runtime path: `policy/runtime/policy_registry.json`

## Executed Steps and Results

### 1) Upsert (`06_policy_registry_upsert`)
- Input:
  - `workflow_id=daily_it_security_digest_mailer_executor_v1`
  - `task_type=security_digest_mail`
- Result:
  - Upsert succeeded
  - DB confirmed row exists in `policy_workflows`

### 2) Publish (`07_policy_registry_publish`)
- Request:
  - `revision_id=rev-e2e-20260222-01`
  - `actor=e2e-test`
- Response:
```json
{
  "status": "ok",
  "action": "publish",
  "revision_id": "rev-e2e-20260222-01",
  "published_count": 1,
  "bundle_publish": {
    "ok": true,
    "revision_id": "rev-e2e-20260222-01",
    "count": 1
  },
  "bundle_server": {
    "ok": true
  }
}
```

### 3) OPA reflection check
- Query target: `security_digest_mail`
- Response:
```json
{
  "result": {
    "allow": true,
    "decision": "allow",
    "policy_id": "executor-core-v1",
    "policy_version": "2026-02-20",
    "reasons": [],
    "requires_approval": false,
    "risk_score": 0
  }
}
```

### 4) Executor dispatch (`04_executor_dispatch`)
- Request id: `e2e-exec-20260222-01`
- Result summary:
  - `status=success`
  - `request_id` non-null
  - `output.task.payload.message` contains LLM-composed digest
  - `output.llm.status=OK`

## Pass/Fail
- PASS

## Notes
- API key header (`X-API-Key`) is required via Caddy policy for `/webhook/*` routes.
- OPA reflection is asynchronous and follows bundle polling interval.
