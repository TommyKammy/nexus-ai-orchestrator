#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
N8N_WEBHOOK_API_KEY="${N8N_WEBHOOK_API_KEY:-ci-local-webhook-key}"
N8N_ENCRYPTION_KEY="${N8N_ENCRYPTION_KEY:-ci-local-encryption-key-32chars}"
SLACK_SIGNING_SECRET="${SLACK_SIGNING_SECRET:-ci-local-slack-signing-secret}"

if [[ -z "$POSTGRES_PASSWORD" ]]; then
  echo "POSTGRES_PASSWORD is required (.env or environment)." >&2
  exit 1
fi

export N8N_WEBHOOK_API_KEY
export N8N_ENCRYPTION_KEY
export SLACK_SIGNING_SECRET

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require_cmd docker
require_cmd jq

prepare_n8n_volume_permissions() {
  # GitHub runners may check out n8n/ owned by a different uid than the container's node user.
  # Ensure n8n can write its runtime config/log files on bind-mounted workspace paths.
  if [[ "${CI:-}" == "true" ]]; then
    mkdir -p "${ROOT_DIR}/n8n"
    chmod a+rwx "${ROOT_DIR}/n8n" || true
    chmod -R a+rwX "${ROOT_DIR}/n8n" || true
  fi
}

POSTGRES_PASSWORD_VAL="$POSTGRES_PASSWORD"
RUN_ID="$(date +%s%N)"
if [[ -z "$RUN_ID" || "$RUN_ID" == *N ]]; then
  RUN_ID="$(date +%s)-$RANDOM$RANDOM"
fi
CI_TENANT_ID="core-e2e-${RUN_ID}"
CI_SCOPE="journey:user-42-${RUN_ID}"
WF_INGEST_NAME="CI Core Journey 01 Memory Ingest ${RUN_ID}"
WF_SEARCH_NAME="CI Core Journey 02 Vector Search ${RUN_ID}"
WF_EXEC_NAME="CI Core Journey 04 Executor Dispatch ${RUN_ID}"
WF_INGEST_PATH="ci/memory/ingest-v3-${RUN_ID}"
WF_SEARCH_PATH="ci/memory/search-v3-${RUN_ID}"
WF_EXEC_PATH="ci/executor/run-${RUN_ID}"
TMP_DIR="$(mktemp -d)"

postgres_exec() {
  docker exec -i ai-postgres env PGPASSWORD="$POSTGRES_PASSWORD_VAL" \
    psql -U ai_user -d ai_memory -v ON_ERROR_STOP=1 "$@"
}

cleanup() {
  if docker ps --format '{{.Names}}' | grep -q '^ai-postgres$'; then
    if ! postgres_exec >/dev/null <<SQL
DELETE FROM workflow_entity
WHERE name IN ('${WF_INGEST_NAME}', '${WF_SEARCH_NAME}', '${WF_EXEC_NAME}');
SQL
    then
      echo "Warning: failed to delete CI workflows during cleanup; manual DB cleanup may be required." >&2
    fi
  fi

  rm -rf "$TMP_DIR"
}

trap cleanup EXIT

CURL_IMAGE="${CURL_IMAGE:-curlimages/curl:8.10.1}"

curl_internal() {
  docker run --rm --network "container:ai-n8n" "${CURL_IMAGE}" "$@"
}

wait_for_ready() {
  local timeout="${1:-300}"
  local start now elapsed
  start="$(date +%s)"

  while true; do
    if curl_internal -sS -o /dev/null -w '%{http_code}' "http://localhost:5678/healthz/readiness" | grep -q '^200$'; then
      return 0
    fi
    now="$(date +%s)"
    elapsed=$((now - start))
    if [[ "$elapsed" -ge "$timeout" ]]; then
      return 1
    fi
    sleep 2
  done
}

echo "[1/8] Starting compose stack..."
prepare_n8n_volume_permissions
COMPOSE_BAKE=false docker compose up -d --build postgres redis policy-bundle-server opa n8n caddy >/dev/null

if ! wait_for_ready 360; then
  echo "n8n readiness check failed." >&2
  docker compose logs n8n --tail 200 >&2 || true
  exit 1
fi

echo "[2/8] Applying base schema migrations..."
POSTGRES_PASSWORD="$POSTGRES_PASSWORD" bash scripts/apply-memory-audit-migration.sh >/dev/null

postgres_exec >/dev/null <<'SQL'
CREATE TABLE IF NOT EXISTS memory_facts (
  id BIGSERIAL PRIMARY KEY,
  subject TEXT NOT NULL,
  predicate TEXT NOT NULL,
  object TEXT NOT NULL,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS memory_episodes (
  id BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  summary TEXT NOT NULL,
  outcome TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  ended_at TIMESTAMPTZ NOT NULL,
  metadata_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
SQL

echo "[3/8] Preparing CI-safe workflow copies..."
cat >"${TMP_DIR}/patch_01.jq" <<'JQ'
(.name) = $name
| (.nodes[] | select(.name=="Webhook") | .parameters.path) = $path
| (.nodes[] | select(.name=="Evaluate Policy")) |= (
    .type = "n8n-nodes-base.code"
    | .typeVersion = 1
    | .parameters = {
      "jsCode": "return [{ json: { result: { allow: true, decision: 'allow', policy_id: 'ci-core-journey', policy_version: 'ci', reasons: [], requires_approval: false, risk_score: 0 } } }];"
    }
    | del(.credentials)
  )
| (.nodes[] | select(.name=="Check Policy")) |= (
    .type = "n8n-nodes-base.code"
    | .typeVersion = 1
    | .parameters = {
      "jsCode": "const validated = $('Check Validation').first().json; return [{ json: { ...validated, policy: { allow: true, decision: 'allow', policy_id: 'ci-core-journey', policy_version: 'ci', reasons: [], requires_approval: false, risk_score: 0 } } }];"
    }
    | del(.credentials)
  )
| (.connections["Check Validation"].main[0]) = [{"node":"Evaluate Policy","type":"main","index":0}]
| (.connections["Check Policy"].main[0]) = [{"node":"Insert Facts","type":"main","index":0}]
| (.nodes[] | select(.name=="Validate and Filter") | .parameters.jsCode) = "const input = $input.first().json.body || {}; const tenantId = String(input.tenant_id || '').trim(); const scope = String(input.scope || '').trim(); const text = String(input.text || '').trim(); const facts = Array.isArray(input.facts) ? input.facts : []; const tags = Array.isArray(input.tags) ? input.tags : []; const source = String(input.source || 'unknown'); if (!tenantId || !scope || !text) { return [{ json: { error: 'Missing required fields: tenant_id, scope, text' } }]; } return [{ json: { tenant_id: tenantId, scope, text, facts: facts.map((f)=>({subject:String(f.subject||'').trim(),predicate:String(f.predicate||'').trim(),object:String(f.object||'').trim(),confidence:Number.isFinite(Number(f.confidence))?Number(f.confidence):1})).filter((f)=>f.subject&&f.predicate&&f.object), tags, source, content_hash: null, request_id: null } }];"
| (.nodes[] | select(.name=="Generate Embedding")) |= (
    .type = "n8n-nodes-base.code"
    | .typeVersion = 1
    | .parameters = {
      "jsCode": "return [{ json: { embedding: { values: Array.from({ length: 1536 }, (_, i) => (i + 1) / 10000) } } }];"
    }
    | del(.credentials)
  )
| (.nodes[] | select(.name=="Parse Embedding") | .parameters.jsCode) = "const original = $('Check Policy').first().json; const embedding = $input.first().json?.embedding?.values; if (!Array.isArray(embedding) || embedding.length === 0) { throw new Error('Invalid mocked embedding'); } return [{ json: { ...original, embedding: `[${embedding.join(',')}]` } }];"
| (.nodes[] | select(.type=="n8n-nodes-base.postgres" and .parameters.additionalFields.queryReplacement != null)) |= (.parameters.options = ((.parameters.options // {}) + {"queryReplacement": .parameters.additionalFields.queryReplacement}))
JQ

cat >"${TMP_DIR}/patch_02.jq" <<'JQ'
(.name) = $name
| (.nodes[] | select(.name=="Webhook") | .parameters.path) = $path
| (.nodes[] | select(.name=="Evaluate Policy")) |= (
    .type = "n8n-nodes-base.code"
    | .typeVersion = 1
    | .parameters = {
      "jsCode": "return [{ json: { result: { allow: true, decision: 'allow', policy_id: 'ci-core-journey', policy_version: 'ci', reasons: [], requires_approval: false, risk_score: 0 } } }];"
    }
    | del(.credentials)
  )
| (.nodes[] | select(.name=="Check Policy")) |= (
    .type = "n8n-nodes-base.code"
    | .typeVersion = 1
    | .parameters = {
      "jsCode": "const validated = $('Check Validation').first().json; return [{ json: { ...validated, policy: { allow: true, decision: 'allow', policy_id: 'ci-core-journey', policy_version: 'ci', reasons: [], requires_approval: false, risk_score: 0 } } }];"
    }
    | del(.credentials)
  )
| (.nodes[] | select(.name=="Generate Query Embedding")) |= (
    .type = "n8n-nodes-base.code"
    | .typeVersion = 1
    | .parameters = {
      "jsCode": "return [{ json: { embedding: { values: Array.from({ length: 1536 }, (_, i) => (i + 1) / 10000) } } }];"
    }
    | del(.credentials)
  )
| (.nodes[] | select(.name=="Parse Embedding") | .parameters.jsCode) = "const original = $('Check Policy').first().json; const embedding = $input.first().json?.embedding?.values; if (!Array.isArray(embedding) || embedding.length === 0) { throw new Error('Invalid mocked embedding'); } return [{ json: { ...original, embedding: `[${embedding.join(',')}]` } }];"
| (.nodes[] | select(.type=="n8n-nodes-base.postgres" and .parameters.additionalFields.queryReplacement != null)) |= (.parameters.options = ((.parameters.options // {}) + {"queryReplacement": .parameters.additionalFields.queryReplacement}))
JQ

cat >"${TMP_DIR}/patch_04.jq" <<'JQ'
(.name) = $name
| (.nodes[] | select(.name=="Webhook") | .parameters.path) = $path
| (.nodes[] | select(.name=="Evaluate Policy")) |= (
    .type = "n8n-nodes-base.code"
    | .typeVersion = 1
    | .parameters = {
      "jsCode": "return [{ json: { result: { allow: true, decision: 'allow', policy_id: 'ci-core-journey', policy_version: 'ci', reasons: [], requires_approval: false, risk_score: 0 } } }];"
    }
    | del(.credentials)
  )
| (.nodes[] | select(.name=="Check Policy")) |= (
    .type = "n8n-nodes-base.code"
    | .typeVersion = 1
    | .parameters = {
      "jsCode": "const validated = $('Check Validation').first().json; return [{ json: { ...validated, policy: { allow: true, decision: 'allow', policy_id: 'ci-core-journey', policy_version: 'ci', reasons: [], requires_approval: false, risk_score: 0 } } }];"
    }
    | del(.credentials)
  )
| (.nodes[] | select(.type=="n8n-nodes-base.postgres" and .parameters.additionalFields.queryReplacement != null)) |= (.parameters.options = ((.parameters.options // {}) + {"queryReplacement": .parameters.additionalFields.queryReplacement}))
JQ

jq --arg name "$WF_INGEST_NAME" --arg path "$WF_INGEST_PATH" \
  -f "${TMP_DIR}/patch_01.jq" n8n/workflows-v3/01_memory_ingest.json >"${TMP_DIR}/01_memory_ingest.json"
jq --arg name "$WF_SEARCH_NAME" --arg path "$WF_SEARCH_PATH" \
  -f "${TMP_DIR}/patch_02.jq" n8n/workflows-v3/02_vector_search.json >"${TMP_DIR}/02_vector_search.json"
jq --arg name "$WF_EXEC_NAME" --arg path "$WF_EXEC_PATH" \
  -f "${TMP_DIR}/patch_04.jq" n8n/workflows-v3/04_executor_dispatch.json >"${TMP_DIR}/04_executor_dispatch.json"

echo "[4/8] Importing credential and CI workflows..."
postgres_exec >/dev/null <<'SQL'
DELETE FROM credentials_entity
WHERE id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';
SQL

jq -n --arg pwd "$POSTGRES_PASSWORD_VAL" \
  '[{"id":"a1b2c3d4-e5f6-7890-abcd-ef1234567890","name":"ai-postgres","type":"postgres","data":{"host":"postgres","port":5432,"database":"ai_memory","user":"ai_user","password":$pwd,"ssl":"disable"}}]' \
  >"${TMP_DIR}/postgres_cred.json"

docker exec -i ai-n8n sh -lc 'cat > /tmp/postgres_cred.json' <"${TMP_DIR}/postgres_cred.json"
docker exec ai-n8n n8n import:credentials --input=/tmp/postgres_cred.json >/dev/null

for wf in 01_memory_ingest.json 02_vector_search.json 04_executor_dispatch.json; do
  docker cp "${TMP_DIR}/${wf}" "ai-n8n:/tmp/${wf}"
  docker exec ai-n8n n8n import:workflow --input="/tmp/${wf}" >/dev/null
  echo "  - imported ${wf}"
done

echo "[5/8] Activating CI workflows..."
postgres_exec >/dev/null <<SQL
UPDATE workflow_entity
SET active = false
WHERE name IN ('${WF_INGEST_NAME}', '${WF_SEARCH_NAME}', '${WF_EXEC_NAME}');

WITH ranked AS (
  SELECT
    id,
    name,
    ROW_NUMBER() OVER (PARTITION BY name ORDER BY "updatedAt" DESC, "createdAt" DESC, id DESC) AS rn
  FROM workflow_entity
  WHERE name IN ('${WF_INGEST_NAME}', '${WF_SEARCH_NAME}', '${WF_EXEC_NAME}')
)
UPDATE workflow_entity w
SET active = true
FROM ranked r
WHERE w.id = r.id
  AND r.rn = 1;

UPDATE workflow_entity w
SET "activeVersionId" = (
  SELECT "versionId"
  FROM workflow_history h
  WHERE h."workflowId" = w.id
  ORDER BY h."createdAt" DESC
  LIMIT 1
)
WHERE w.active = true
  AND w.name IN ('${WF_INGEST_NAME}', '${WF_SEARCH_NAME}', '${WF_EXEC_NAME}');
SQL

echo "[6/8] Restarting n8n to register webhook changes..."
docker compose restart n8n >/dev/null

if ! wait_for_ready 360; then
  echo "n8n readiness check failed after restart." >&2
  docker compose logs n8n --tail 200 >&2 || true
  exit 1
fi

wait_for_webhooks_registered() {
  local timeout="${1:-120}"
  local start now elapsed count
  start="$(date +%s)"

  while true; do
    count="$(postgres_exec -Atc "SELECT COUNT(*) FROM webhook_entity WHERE method='POST' AND \"webhookPath\" IN ('${WF_INGEST_PATH}', '${WF_SEARCH_PATH}', '${WF_EXEC_PATH}');" || echo 0)"
    if [[ "$count" -eq 3 ]]; then
      return 0
    fi

    now="$(date +%s)"
    elapsed=$((now - start))
    if [[ "$elapsed" -ge "$timeout" ]]; then
      echo "Timed out waiting for webhook registration (count=${count})." >&2
      exit 1
    fi

    sleep 2
  done
}

wait_for_webhooks_registered 180

post_webhook() {
  local path="$1"
  local payload="$2"
  local response http_code body
  response="$(
    curl_internal -sS -w $'\n%{http_code}' -H "Content-Type: application/json" \
      -H "X-API-Key: ${N8N_WEBHOOK_API_KEY}" \
      -X POST "http://localhost:5678/webhook/${path}" \
      -d "$payload"
  )"
  http_code="${response##*$'\n'}"
  body="${response%$'\n'*}"

  if [[ "$http_code" != "200" ]]; then
    echo "Webhook call failed for ${path}: HTTP ${http_code}" >&2
    if [[ -n "$body" ]]; then
      echo "Webhook response body for ${path}:" >&2
      echo "$body" >&2
    fi
    echo "Recent n8n logs:" >&2
    docker compose logs n8n --tail 100 >&2 || true
    exit 1
  fi
}

echo "[7/8] Running core journey webhooks..."
INGEST_PAYLOAD="$(
  jq -cn \
    --arg tenant "$CI_TENANT_ID" \
    --arg scope "$CI_SCOPE" \
    --arg text "User prefers PDF reports" \
    --arg source "compose_e2e" \
    '{"tenant_id":$tenant,"scope":$scope,"text":$text,"facts":[{"subject":"user:42","predicate":"prefers","object":"PDF","confidence":0.95}],"tags":["preference"],"source":$source}'
)"
SEARCH_PAYLOAD="$(
  jq -cn \
    --arg tenant "$CI_TENANT_ID" \
    --arg scope "$CI_SCOPE" \
    '{"tenant_id":$tenant,"scope":$scope,"query":"PDF","k":3}'
)"
EXEC_PAYLOAD="$(
  jq -cn \
    --arg tenant "$CI_TENANT_ID" \
    --arg scope "$CI_SCOPE" \
    '{"tenant_id":$tenant,"scope":$scope,"task":{"type":"ping","message":"hello"}}'
)"

post_webhook "$WF_INGEST_PATH" "$INGEST_PAYLOAD"
post_webhook "$WF_SEARCH_PATH" "$SEARCH_PAYLOAD"
post_webhook "$WF_EXEC_PATH" "$EXEC_PAYLOAD"

wait_for_success() {
  local workflow_name="$1"
  local timeout="${2:-120}"
  local start now elapsed status
  start="$(date +%s)"

  while true; do
    status="$(postgres_exec -Atc "SELECT COALESCE(e.status,'') || '|' || COALESCE(e.finished::text,'') FROM execution_entity e JOIN workflow_entity w ON w.id=e.\"workflowId\" WHERE w.name='${workflow_name}' ORDER BY e.id DESC LIMIT 1;" || true)"
    if [[ "$status" == "success|true" ]]; then
      return 0
    fi
    if [[ "$status" == error* ]]; then
      echo "Execution failed for ${workflow_name}: ${status}" >&2
      exit 1
    fi

    now="$(date +%s)"
    elapsed=$((now - start))
    if [[ "$elapsed" -ge "$timeout" ]]; then
      echo "Timed out waiting for execution success: ${workflow_name} (last=${status})" >&2
      exit 1
    fi
    sleep 2
  done
}

wait_for_success "$WF_INGEST_NAME"
wait_for_success "$WF_SEARCH_NAME"
wait_for_success "$WF_EXEC_NAME"

echo "[8/8] Verifying database side effects..."
VECTOR_COUNT="$(postgres_exec -Atc "SELECT COUNT(*) FROM memory_vectors WHERE tenant_id='${CI_TENANT_ID}' AND scope='${CI_SCOPE}';")"
EPISODE_COUNT="$(postgres_exec -Atc "SELECT COUNT(*) FROM memory_episodes WHERE tenant_id='${CI_TENANT_ID}' AND scope='${CI_SCOPE}';")"

if [[ "${VECTOR_COUNT}" -lt 1 ]]; then
  echo "Expected at least one memory_vectors row for ${CI_TENANT_ID}/${CI_SCOPE}." >&2
  exit 1
fi

if [[ "${EPISODE_COUNT}" -lt 1 ]]; then
  echo "Expected at least one memory_episodes row for ${CI_TENANT_ID}/${CI_SCOPE}." >&2
  exit 1
fi

echo "Core compose E2E journey passed."
