#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${K8S_NAMESPACE:-executor-system}"
SERVICE_NAME="${K8S_SERVICE_NAME:-executor-load-balancer}"
LOCAL_PORT="${K8S_LOCAL_PORT:-18080}"
BASE_URL="${K8S_TARGET_URL:-http://127.0.0.1:${LOCAL_PORT}}"
ARTIFACT_DIR="${K8S_TEST_ARTIFACT_DIR:-artifacts/k8s-tests}"
ROLL_OUT_TIMEOUT="${SMOKE_ROLLOUT_TIMEOUT:-180s}"
REQUIRED_DEPLOYMENTS="${SMOKE_REQUIRED_DEPLOYMENTS:-redis executor-load-balancer}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "${ARTIFACT_DIR}"
RESOURCE_SNAPSHOT="${ARTIFACT_DIR}/k8s-smoke-resources-${TIMESTAMP}.txt"
REPORT_FILE="${ARTIFACT_DIR}/k8s-smoke-report-${TIMESTAMP}.md"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required but was not found in PATH." >&2
  exit 1
fi

kubectl get deploy,svc,ingress -n "${NAMESPACE}" > "${RESOURCE_SNAPSHOT}"

for dep in ${REQUIRED_DEPLOYMENTS}; do
  kubectl rollout status "deployment/${dep}" -n "${NAMESPACE}" --timeout="${ROLL_OUT_TIMEOUT}" >/dev/null
done

PF_PID=""
cleanup() {
  if [[ -n "${PF_PID}" ]] && kill -0 "${PF_PID}" >/dev/null 2>&1; then
    kill "${PF_PID}" >/dev/null 2>&1 || true
    wait "${PF_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [[ -z "${K8S_TARGET_URL:-}" ]]; then
  PORT_FORWARD_LOG="/tmp/k8s-smoke-port-forward.log"
  kubectl -n "${NAMESPACE}" port-forward "svc/${SERVICE_NAME}" "${LOCAL_PORT}:80" >"${PORT_FORWARD_LOG}" 2>&1 &
  PF_PID=$!
  READINESS_OK=0
  for _ in $(seq 1 20); do
    if curl --connect-timeout 3 --max-time 5 -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
      READINESS_OK=1
      break
    fi
    sleep 1
  done
  if [[ "${READINESS_OK}" -ne 1 ]]; then
    echo "Smoke test failed: /health not reachable at ${BASE_URL}/health after port-forward wait." >&2
    if [[ -f "${PORT_FORWARD_LOG}" ]]; then
      sed 's/^/  /' "${PORT_FORWARD_LOG}" >&2 || cat "${PORT_FORWARD_LOG}" >&2
    fi
    exit 1
  fi
fi

HEALTH_HTTP_CODE="$(curl --connect-timeout 5 --max-time 10 -sS -o /tmp/k8s-smoke-health.json -w '%{http_code}' "${BASE_URL}/health" || echo '000')"
STATS_HTTP_CODE="$(curl --connect-timeout 5 --max-time 10 -sS -o /tmp/k8s-smoke-stats.json -w '%{http_code}' "${BASE_URL}/stats" || echo '000')"

if [[ "${HEALTH_HTTP_CODE}" != "200" ]]; then
  echo "Smoke test failed: /health returned HTTP ${HEALTH_HTTP_CODE}" >&2
  exit 1
fi

if [[ "${STATS_HTTP_CODE}" != "200" ]]; then
  echo "Smoke test failed: /stats returned HTTP ${STATS_HTTP_CODE}" >&2
  exit 1
fi

cat > "${REPORT_FILE}" <<EOF
# K8s Smoke Test Report

- timestamp: ${TIMESTAMP}
- namespace: ${NAMESPACE}
- service: ${SERVICE_NAME}
- base_url: ${BASE_URL}

## Deployment Readiness
- required deployments: ${REQUIRED_DEPLOYMENTS}
- rollout timeout: ${ROLL_OUT_TIMEOUT}

## HTTP Checks
- GET /health: ${HEALTH_HTTP_CODE}
- GET /stats: ${STATS_HTTP_CODE}

## /health response
\`\`\`json
$(cat /tmp/k8s-smoke-health.json)
\`\`\`

## /stats response
\`\`\`json
$(cat /tmp/k8s-smoke-stats.json)
\`\`\`

## Resource Snapshot
\`\`\`text
$(cat "${RESOURCE_SNAPSHOT}")
\`\`\`
EOF

cp "${REPORT_FILE}" "${ARTIFACT_DIR}/k8s-smoke-report-latest.md"

echo "Smoke test passed."
echo "Report: ${REPORT_FILE}"
