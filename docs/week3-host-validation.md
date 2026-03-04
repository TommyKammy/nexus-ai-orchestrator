# Week3 Host-Side Validation Guide

This guide defines the validation steps to run on the hosting server for Week3 deliverables (Policy Registry lightweight UI and publish flow).

## 1) Deploy and service health

```bash
cd /opt/ai-orchestrator
./deploy-updates.sh
```

Expected:
- `ai-policy-bundle-server`, `ai-caddy`, `ai-n8n`, `ai-opa` are `Up`.
- `policy-ui` route check is validated by deploy script.

## 2) UI availability

Open:
- `https://<your-host>/policy-ui/`

Expected:
- `Policy Registry Console` page renders.
- Sections are visible: `Rules`, `Upsert Rule`, `Publish Revision`, `Runtime Registry`, `Last Response`.

## 3) Backend/UI API connectivity (from host)

```bash
curl -sS http://127.0.0.1:8088/policy-ui/api/current | jq .
curl -sS http://127.0.0.1:8088/policy-ui/api/list | jq .
```

Expected:
- JSON responses are returned.
- `list` response includes `status: ok` and `items`.

## 4) Upsert test via UI

In `Upsert Rule`, submit:
- `workflow_id`: `daily_it_security_digest_mailer_executor_v1`
- `task_type`: `security_digest_mail`
- `tenant_id`: `*`
- `scope_pattern`: `*`
- `enabled`: `true`
- `constraints`: `{}`

Expected:
- `Last Response` shows `status: ok`, `action: upsert`.
- The rule appears in the `Rules` table.

## 5) Publish test via UI

In `Publish Revision`, submit:
- `revision_id`: `rev-week3-ui-<timestamp>`
- `actor`: `week3-test`
- `notes`: `week3 host validation`

Expected:
- Confirmation dialog appears.
- Publish request succeeds.
- `Last Response.reflection.reflected` becomes `true` (allow up to 30 seconds).
- `Runtime Registry` shows the same `revision_id`.

## 6) OPA reflection check

```bash
curl -sS http://127.0.0.1:8181/v1/data/ai/policy/result \
  -H 'Content-Type: application/json' \
  --data-raw '{
    "input": {
      "action": "executor.execute",
      "subject": { "tenant_id": "security-digest", "scope": "daily-mailer", "role": "workflow" },
      "resource": { "tenant_id": "security-digest", "scope": "daily-mailer", "task_type": "security_digest_mail", "template": "n8n-dispatch" },
      "context": { "request_id": "week3-opa-check", "network_enabled": false, "payload_size": 100 }
    }
  }' | jq .
```

Expected:
- `result.allow = true`
- `result.decision = "allow"`

## 7) End-to-end dispatch test (`04_executor_dispatch`)

```bash
curl -X POST 'https://<your-host>/webhook/executor/run' \
  -H 'X-API-Key: <WEBHOOK_API_KEY>' \
  -H 'Content-Type: application/json' \
  --data-raw '{
    "tenant_id": "security-digest",
    "scope": "daily-mailer",
    "request_id": "week3-exec-01",
    "task": {
      "type": "security_digest_mail",
      "template": "daily_it_security_digest",
      "llm": {
        "provider": "openrouter",
        "model": "qwen/qwen3-next-80b-a3b-instruct:free",
        "selectedBy": "week3-ui-test"
      },
      "payload": {
        "recipient": "you@example.com",
        "subject": "[Week3 Test]",
        "message": "fact block",
        "htmlMessage": "<p>fact block</p>",
        "source_stats": {
          "kev_total": 1526,
          "nvd_count": 20
        }
      }
    }
  }'
```

Expected:
- `status = success`
- `request_id` is non-null
- `output.task.payload.message` contains final digest text

## 8) Negative test (deny path)

Run the same dispatch request with an unregistered `task.type` (for example, `unknown_week3_task`).

Expected:
- `status = error`
- error indicates policy denial (for example `task_type_not_allowed`)

## 9) Evidence and audit verification

```bash
docker exec -i ai-postgres psql -U ai_user -d ai_memory -c "select revision_id,status,is_active,published_at from policy_revisions order by published_at desc limit 5;"
docker exec -i ai-postgres psql -U ai_user -d ai_memory -c "select action,actor,result,created_at from policy_publish_logs order by created_at desc limit 10;"
```

Expected:
- latest publish revisions are recorded
- publish/upsert actions are visible in logs

## 10) Minimal failure-mode test

Submit invalid JSON in `constraints` field from UI.

Expected:
- UI validation error is shown
- no upsert is executed

---

## Pass criteria
- All expected results above are satisfied.
- No OPA restart is required for policy reflection.
- UI and webhook/API paths behave consistently with audit visibility.
