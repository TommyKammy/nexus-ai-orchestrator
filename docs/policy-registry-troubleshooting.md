# Policy Registry Troubleshooting

## Symptom: `relation "policy_workflows" does not exist`
Cause:
- DB schema migration not applied (or wrong DB selected in n8n credential).

Fix:
1. Apply SQL: `sql/20260222_policy_registry.sql`
2. Verify n8n postgres credential points to `ai_memory`

## Symptom: `Unauthorized: Invalid or missing API key`
Cause:
- Caddy protects `/webhook/*` with `X-API-Key`.

Fix:
- Add `X-API-Key` header in curl/client requests.

## Symptom: Publish succeeded but OPA decision unchanged
Cause:
- OPA bundle polling delay (10-30 sec)
- runtime registry not updated
- bundle-server old container image still running

Fix:
1. Check `GET /registry/current`
2. Wait up to 30 sec and re-test
3. Rebuild/restart `policy-bundle-server` if needed

## Symptom: Bundle publish timeout (`ECONNABORTED`)
Cause:
- transient network/container latency during publish call

Fix:
1. Ensure latest `07_policy_registry_publish` is imported (timeout 30s + retry enabled)
2. Re-run publish request
3. If runtime registry is updated, wait for OPA polling window and verify via OPA endpoint

## Symptom: host update requires manual file copy from `/tmp`
Cause:
- non-git deployment path with local drift

Fix:
1. Use git-based update flow on host:
   - `git fetch && git rebase origin/main`
   - `./deploy.sh` (includes Caddy + policy-ui validation)
2. Or run `./deploy-updates.sh` in `/opt/ai-orchestrator`

## Symptom: `status=success` but `request_id` is null in dispatch response
Cause:
- `04_executor_dispatch` response mapped from DB node output instead of finalized payload.

Fix:
- Ensure latest `04_executor_dispatch.json` with `Finalize Success Payload` node is imported.

## Symptom: OPA bundle recursion errors
Cause:
- Rego rule references `data` in a way that creates recursive dependency.

Fix:
- Use direct base document references (for example `data.policy_registry`) and re-check with `opa check`.
