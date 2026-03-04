# Policy Registry E2E Checklist (TKT-18)

## Objective
Validate end-to-end path:
`06 upsert -> 07 publish -> OPA reflect -> 04_executor_dispatch`

## Test Data
- workflow_id: `daily_it_security_digest_mailer_executor_v1`
- task_type: `security_digest_mail`
- tenant/scope: `security-digest` / `daily-mailer`
- revision_id: unique per run

## Steps

1. Upsert rule (`06`)
- Expected: `status=ok`, `action=upsert`

2. Publish revision (`07`)
- Expected: `status=ok`, `bundle_publish.ok=true`

3. Confirm bundle runtime
- `GET /registry/current` includes revision and workflow rule

4. Confirm OPA reflection
- Wait 10-30 sec
- Policy query returns `allow=true` for `security_digest_mail`

5. Execute dispatch (`04`)
- POST `/webhook/executor/run` with `task.type=security_digest_mail`
- Expected:
  - `status=success`
  - `request_id` non-null
  - `output.task.payload.message` populated
  - if LLM available, output includes generated digest content

6. Negative test (deny)
- Execute with unregistered `task.type`
- Expected: `status=error`, `message=Policy denied`, `task_type_not_allowed`

## Pass Criteria
- All expected responses matched
- Decision transitions are consistent
- No manual OPA restart required

## Evidence to capture
- Request/response payloads for 06/07/04
- OPA decision response JSON
- n8n execution IDs/screenshots
- DB snippets (`policy_revisions`, `policy_publish_logs`)

## Latest Evidence
- `docs/policy-registry-e2e-evidence-20260222.md`
