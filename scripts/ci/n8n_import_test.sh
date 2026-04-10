#!/usr/bin/env bash
set -euo pipefail

echo "=========================================="
echo "N8N Import + Execution Test (Postgres)"
echo "=========================================="
echo ""

# Images
N8N_IMAGE="${N8N_IMAGE:-n8nio/n8n:2.8.3}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-postgres:18-alpine}"

# Docker resources
NETWORK_NAME="${NETWORK_NAME:-n8n-ci-net}"
N8N_CONTAINER="${N8N_CONTAINER:-n8n-ci-test}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-n8n-ci-postgres}"

# Postgres settings (CI only)
POSTGRES_DB="${POSTGRES_DB:-n8n}"
POSTGRES_USER="${POSTGRES_USER:-n8n}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-n8n}"

# n8n settings
N8N_PORT="${N8N_PORT:-5678}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-480}"
N8N_ENCRYPTION_KEY="${N8N_ENCRYPTION_KEY:-test-key-for-ci-only}"
N8N_WEBHOOK_API_KEY="${N8N_WEBHOOK_API_KEY:-ci-local-webhook-key}"
WEBHOOK_BASE_URL="${WEBHOOK_BASE_URL:-http://localhost:${N8N_PORT}}"

# Workflows
WORKFLOW_DIR="${PWD}/n8n/workflows-v3"
WORKFLOW_FILES=()
SLACK_WORKFLOW_NAME="${SLACK_WORKFLOW_NAME:-slack_chat_minimal_v1}"
ROUTER_WORKFLOW_NAME="${ROUTER_WORKFLOW_NAME:-Chat Router v1 (Adaptive Routing)}"

CI_IMPORT_DIR=""
WORKLOG="${WORKLOG:-/dev/null}"

cleanup() {
  if [[ "${SKIP_CLEANUP:-0}" == "1" ]]; then
    echo ""
    echo "[cleanup] SKIP_CLEANUP=1, leaving containers/network/tmp in place for inspection."
    return 0
  fi
  echo ""
  echo "[cleanup] Removing containers/network/tmp..."
  docker rm -f -v "${N8N_CONTAINER}" >/dev/null 2>&1 || true
  docker rm -f -v "${POSTGRES_CONTAINER}" >/dev/null 2>&1 || true
  docker network rm "${NETWORK_NAME}" >/dev/null 2>&1 || true
  if [[ -n "${CI_IMPORT_DIR}" && -d "${CI_IMPORT_DIR}" ]]; then
    rm -rf "${CI_IMPORT_DIR}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

die() {
  echo "ERROR: $*" >&2
  echo ""
  echo "[debug] n8n logs (tail 200):"
  docker logs "${N8N_CONTAINER}" --tail 200 2>/dev/null || true
  echo ""
  echo "[debug] postgres logs (tail 200):"
  docker logs "${POSTGRES_CONTAINER}" --tail 200 2>/dev/null || true
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

wait_for_http_200() {
  local url="$1"
  local timeout="$2"
  local start now elapsed
  start="$(date +%s)"
  while true; do
    if curl -fsS "$url" >/dev/null 2>&1; then
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

wait_for_n8n_ready() {
  local timeout="$1"
  local label="$2"
  local start now elapsed
  start="$(date +%s)"
  
  echo "      Waiting for n8n readiness (${label})..."
  while true; do
    # Try /healthz/readiness first (preferred, no auth)
    if curl -fsS "${WEBHOOK_BASE_URL}/healthz/readiness" >/dev/null 2>&1; then
      echo "      n8n ready via /healthz/readiness"
      return 0
    fi
    # Fallback to /healthz
    if curl -fsS "${WEBHOOK_BASE_URL}/healthz" >/dev/null 2>&1; then
      echo "      n8n ready via /healthz"
      return 0
    fi
    # Fallback to /rest/health
    if curl -fsS "${WEBHOOK_BASE_URL}/rest/health" >/dev/null 2>&1; then
      echo "      n8n ready via /rest/health"
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

normalize_and_write() {
  local src="$1"
  local dst="$2"

  python3 - "$src" "$dst" <<'PY'
import json, sys

src, dst = sys.argv[1], sys.argv[2]
with open(src, "r", encoding="utf-8") as f:
    data = json.load(f)

def normalize_workflow(obj):
    # Ensure required fields exist for import stability
    if isinstance(obj, dict):
        obj.setdefault("active", False)  # import may ignore; we activate later via CLI
        # n8n import in CI fails when exported string tags are mapped without tag entities.
        # Keep smoke test focused on importability of workflow graphs, not tag metadata.
        obj["tags"] = []
    return obj

if isinstance(data, dict):
    out = [normalize_workflow(data)]
elif isinstance(data, list):
    out = [normalize_workflow(x) for x in data]
else:
    raise SystemExit(f"Unsupported JSON root type: {type(data)}")

with open(dst, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
PY
}

extract_router_path() {
  python3 - <<'PY'
import json, sys
p = "n8n/workflows-v3/chat_router_v1.json"
with open(p, "r", encoding="utf-8") as f:
    w = json.load(f)

nodes = w.get("nodes", [])
for n in nodes:
    if n.get("type") == "n8n-nodes-base.webhook":
        path = (n.get("parameters") or {}).get("path")
        if path:
            # Normalize leading slash if any
            path = path.lstrip("/")
            print(path)
            sys.exit(0)

sys.exit("No webhook node path found in chat_router_v1.json")
PY
}

discover_workflows() {
  WORKFLOW_FILES=()
  while IFS= read -r workflow_file; do
    WORKFLOW_FILES+=("${workflow_file}")
  done < <(
    find "${WORKFLOW_DIR}" -maxdepth 1 -type f -name '*.json' -exec basename {} \; | sort
  )

  if [[ "${#WORKFLOW_FILES[@]}" -eq 0 ]]; then
    die "No workflow JSON files found under ${WORKFLOW_DIR}"
  fi
}

main() {
  require_cmd docker
  require_cmd curl
  require_cmd python3

  [[ -d "${WORKFLOW_DIR}" ]] || die "Workflow directory not found: ${WORKFLOW_DIR}"
  discover_workflows

  echo "WORKFLOW_DIR=${WORKFLOW_DIR}"
  echo "WORKFLOW_COUNT=${#WORKFLOW_FILES[@]}"
  ls -la "${WORKFLOW_DIR}" || true
  echo ""

  echo "Creating CI import files..."
  mkdir -p "${PWD}/.tmp"
  CI_IMPORT_DIR="$(mktemp -d "${PWD}/.tmp/n8n-import.XXXXXX")"
  [[ -w "${CI_IMPORT_DIR}" ]] || die "Temp dir not writable: ${CI_IMPORT_DIR}"

  for wf in "${WORKFLOW_FILES[@]}"; do
    if [[ -f "${WORKFLOW_DIR}/${wf}" ]]; then
      normalize_and_write "${WORKFLOW_DIR}/${wf}" "${CI_IMPORT_DIR}/${wf}"
      echo "  - Normalized ${wf} -> ${CI_IMPORT_DIR}/${wf}"
    else
      echo "  - WARNING: missing workflow file: ${wf} (skipping)"
    fi
  done

  chmod -R a+rX "${CI_IMPORT_DIR}"
  ls -la "${CI_IMPORT_DIR}" || true
  echo ""

  echo "[CI] Creating docker network: ${NETWORK_NAME}"
  docker network create "${NETWORK_NAME}" >/dev/null

  echo "[CI] Starting Postgres container..."
  docker run -d --name "${POSTGRES_CONTAINER}" --network "${NETWORK_NAME}" \
    -e POSTGRES_DB="${POSTGRES_DB}" \
    -e POSTGRES_USER="${POSTGRES_USER}" \
    -e POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
    "${POSTGRES_IMAGE}" >/dev/null

  echo "[CI] Waiting for Postgres readiness..."
  local start now elapsed
  start="$(date +%s)"
  while true; do
    if docker exec "${POSTGRES_CONTAINER}" pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
      echo "Postgres ready."
      break
    fi
    now="$(date +%s)"
    elapsed=$((now - start))
    if [[ "$elapsed" -ge "${TIMEOUT_SECONDS}" ]]; then
      die "Postgres failed to become ready within ${TIMEOUT_SECONDS}s"
    fi
    sleep 2
  done
  echo ""

  echo "[1/5] Importing workflows (before starting n8n to avoid migration conflicts)..."
  # Import into fresh database using temporary container (runs migrations once)
  for wf in "${WORKFLOW_FILES[@]}"; do
    if [[ -f "${WORKFLOW_DIR}/${wf}" ]]; then
      echo "      Importing ${wf}..."
      docker run --rm --network "${NETWORK_NAME}" \
        -e DB_TYPE=postgresdb \
        -e DB_POSTGRESDB_HOST="${POSTGRES_CONTAINER}" \
        -e DB_POSTGRESDB_PORT=5432 \
        -e DB_POSTGRESDB_DATABASE="${POSTGRES_DB}" \
        -e DB_POSTGRESDB_USER="${POSTGRES_USER}" \
        -e DB_POSTGRESDB_PASSWORD="${POSTGRES_PASSWORD}" \
        -e N8N_DIAGNOSTICS_ENABLED=false \
        -e N8N_PERSONALIZATION_ENABLED=false \
        -e N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=false \
        -v "${CI_IMPORT_DIR}:/import:ro" \
        "${N8N_IMAGE}" import:workflow --input="/import/${wf}" >/dev/null
      echo "      Imported ${wf}"
    fi
  done
  imported_count="$(docker exec -i "${POSTGRES_CONTAINER}" psql -tA -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c 'SELECT COUNT(*) FROM workflow_entity;')"
  imported_count="${imported_count//[[:space:]]/}"
  if [[ -z "${imported_count}" || "${imported_count}" -lt "${#WORKFLOW_FILES[@]}" ]]; then
    die "Expected at least ${#WORKFLOW_FILES[@]} imported workflows, found ${imported_count:-0}"
  fi
  echo "      Imported workflows in DB: ${imported_count}"
  echo ""

  echo "[2/5] Inspecting schema and activating workflows..."
  echo "      Inspecting workflow_entity schema..."
  docker exec -i "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "\d workflow_entity" 2>&1 | tee -a "$WORKLOG"
  
  echo "      Current workflows in DB (before activation):"
  docker exec -i "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
SELECT id, name, active FROM workflow_entity ORDER BY id;
" 2>&1 | tee -a "$WORKLOG"
  
  echo "      Activating workflows via SQL..."
  docker exec -i "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" <<SQL | tee -a "$WORKLOG"
-- Update active status
UPDATE workflow_entity 
SET active = true 
WHERE name IN ('${SLACK_WORKFLOW_NAME}', '${ROUTER_WORKFLOW_NAME}');

-- Set activeVersionId to the latest version for each active workflow (required for n8n 2.8.3)
UPDATE workflow_entity w
SET "activeVersionId" = (
  SELECT "versionId" FROM workflow_history h 
  WHERE h."workflowId" = w.id 
  ORDER BY h."createdAt" DESC 
  LIMIT 1
)
WHERE w.active = true;

SELECT id, name, active, "activeVersionId" FROM workflow_entity WHERE active = true;
SQL

  active_required_count="$(
    docker exec -i "${POSTGRES_CONTAINER}" psql -tA -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c \
      "SELECT COUNT(*) FROM workflow_entity WHERE active = true AND name IN ('${SLACK_WORKFLOW_NAME}', '${ROUTER_WORKFLOW_NAME}');"
  )"
  active_required_count="${active_required_count//[[:space:]]/}"
  if [[ "${active_required_count}" != "2" ]]; then
    die "Expected 2 active smoke-test workflows (${SLACK_WORKFLOW_NAME}, ${ROUTER_WORKFLOW_NAME}), found ${active_required_count:-0}"
  fi
  
  echo "      Activation complete."
  echo ""

  echo "[3/5] Starting n8n to register webhooks..."
  docker run -d --name "${N8N_CONTAINER}" --network "${NETWORK_NAME}" \
    -p "${N8N_PORT}:5678" \
    -e DB_TYPE=postgresdb \
    -e DB_POSTGRESDB_HOST="${POSTGRES_CONTAINER}" \
    -e DB_POSTGRESDB_PORT=5432 \
    -e DB_POSTGRESDB_DATABASE="${POSTGRES_DB}" \
    -e DB_POSTGRESDB_USER="${POSTGRES_USER}" \
    -e DB_POSTGRESDB_PASSWORD="${POSTGRES_PASSWORD}" \
    -e N8N_DIAGNOSTICS_ENABLED=false \
    -e N8N_PERSONALIZATION_ENABLED=false \
    -e N8N_USER_MANAGEMENT_DISABLED=true \
    -e N8N_BASIC_AUTH_ACTIVE=false \
    -e N8N_ENCRYPTION_KEY="${N8N_ENCRYPTION_KEY}" \
    -e N8N_WEBHOOK_API_KEY="${N8N_WEBHOOK_API_KEY}" \
    -e N8N_BLOCK_ENV_ACCESS_IN_NODE=false \
    -e WEBHOOK_URL="${WEBHOOK_BASE_URL}" \
    -e N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=false \
    -e SLACK_SIG_VERIFY_ENABLED=false \
    -e N8N_PUBLIC_API_DISABLED=true \
    -e CI=true \
    -e APP_ENV=ci \
    "${N8N_IMAGE}" > /dev/null

  if wait_for_n8n_ready "${TIMEOUT_SECONDS}" "after activation"; then
    :
  else
    die "n8n failed to become ready after restart within ${TIMEOUT_SECONDS}s"
  fi
  echo ""

  echo "[4/5] Verifying activation and router webhook auth contract..."
  
  # Deterministic verification 1: DB shows workflows active (already verified in step 4)
  echo "      Checking DB activation state..."
  docker exec -i "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
SELECT id, name, active FROM workflow_entity WHERE active = true;
" 2>&1 | tee -a "$WORKLOG"
  
  echo "      Checking n8n logs for workflow activation..."
  docker logs --tail 200 "${N8N_CONTAINER}" 2>&1 | tee /tmp/n8n_tail.log | tee -a "$WORKLOG"
  grep -q "Start Active Workflows\|Initializing active workflows\|Started with workflow" /tmp/n8n_tail.log || echo "      Log message variants not found, relying on DB activation state"
  grep -q "slack_chat_minimal_v1" /tmp/n8n_tail.log || echo "      Workflow name not in logs, relying on DB state"
  grep -q "Chat Router v1" /tmp/n8n_tail.log || echo "      Workflow name not in logs, relying on DB state"
  echo "      Activation verified (DB shows active=true)."
  
  echo "      Waiting 5s for webhooks to register..."
  sleep 5
   
  # Extract router path and call webhook
  local router_path
  router_path="$(extract_router_path)" || die "Failed to extract router webhook path from chat_router_v1.json"
  [[ -n "${router_path}" ]] || die "Empty router webhook path extracted"
  echo "Router webhook path: ${router_path}"

  WEBHOOK_URL="${WEBHOOK_BASE_URL}/webhook/${router_path}"
  # Payload must match what chat_router_v1 expects: tenant_id, scope, message (or text)
  PAYLOAD='{"tenant_id":"ci-tenant","scope":"ci-test","text":"ci test message","brain_enabled":false}'

  echo "      Calling webhook without auth: ${WEBHOOK_URL}"
  HTTP_STATUS="$(curl -sS -o /tmp/webhook_body.txt -w '%{http_code}' \
    -X POST \
    -H 'Content-Type: application/json' \
    -d "${PAYLOAD}" "${WEBHOOK_URL}" \
    2>/tmp/webhook_err.txt || true)"
  BODY="$(cat /tmp/webhook_body.txt 2>/dev/null || true)"
  ERR="$(cat /tmp/webhook_err.txt 2>/dev/null || true)"

  echo "      HTTP Status (no auth): ${HTTP_STATUS}"
  echo "      Body (no auth): ${BODY}"
  if [[ -n "${ERR}" ]]; then
    echo "      Curl stderr (no auth): ${ERR}"
  fi

  if [[ "${HTTP_STATUS}" != "401" ]]; then
    echo ""
    echo "ERROR: Webhook endpoint did not reject unauthenticated request"
    echo ""
    echo "[debug] n8n logs (tail 400):"
    docker logs --tail 400 "${N8N_CONTAINER}" 2>&1 | tee -a "$WORKLOG"
    die "router webhook unauthenticated call expected 401 got ${HTTP_STATUS}"
  fi

  if ! echo "${BODY}" | grep -q '"status"[[:space:]]*:[[:space:]]*"error"'; then
    die "router webhook unauthenticated response did not include status=error"
  fi

  echo "      Calling webhook with auth: ${WEBHOOK_URL}"
  HTTP_STATUS="$(curl -sS -o /tmp/webhook_body.txt -w '%{http_code}' \
    -X POST \
    -H 'Content-Type: application/json' \
    -H "X-API-Key: ${N8N_WEBHOOK_API_KEY}" \
    -d "${PAYLOAD}" "${WEBHOOK_URL}" \
    2>/tmp/webhook_err.txt || true)"
  BODY="$(cat /tmp/webhook_body.txt 2>/dev/null || true)"
  ERR="$(cat /tmp/webhook_err.txt 2>/dev/null || true)"

  echo "      HTTP Status (auth): ${HTTP_STATUS}"
  echo "      Body (auth): ${BODY}"
  if [[ -n "${ERR}" ]]; then
    echo "      Curl stderr (auth): ${ERR}"
  fi

  if [[ "${HTTP_STATUS}" != "200" ]]; then
    echo ""
    echo "ERROR: Webhook endpoint returned non-200 status"
    echo ""
    echo "[debug] Recent executions (execution_entity)..."
    docker exec -i "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
SELECT id, \"workflowId\", status, \"startedAt\", \"stoppedAt\"
FROM execution_entity
ORDER BY \"startedAt\" DESC
LIMIT 5;
" 2>&1 | tee -a "$WORKLOG"
    echo ""
    echo "[debug] Recent execution_data (error details)..."
    docker exec -i "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
SELECT \"executionId\", LEFT(data::text, 2000) AS data_snippet
FROM execution_data
ORDER BY \"executionId\" DESC
LIMIT 3;
" 2>&1 | tee -a "$WORKLOG"
    echo ""
    echo "[debug] n8n logs (tail 400):"
    docker logs --tail 400 "${N8N_CONTAINER}" 2>&1 | tee -a "$WORKLOG"
    die "router webhook authenticated call failed, expected 200 got ${HTTP_STATUS}"
  fi

  if ! echo "${BODY}" | grep -q '"status"[[:space:]]*:[[:space:]]*"NO_BRAIN"'; then
    die "router webhook authenticated response did not return status=NO_BRAIN"
  fi

  echo ""
  echo "=========================================="
  echo "✓ ALL CHECKS PASSED"
  echo "=========================================="
}

main "$@"
