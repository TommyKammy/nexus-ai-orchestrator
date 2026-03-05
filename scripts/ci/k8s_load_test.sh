#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${K8S_NAMESPACE:-executor-system}"
SERVICE_NAME="${K8S_SERVICE_NAME:-executor-load-balancer}"
LOCAL_PORT="${K8S_LOCAL_PORT:-18080}"
BASE_URL="${K8S_TARGET_URL:-http://127.0.0.1:${LOCAL_PORT}}"
LOAD_ENDPOINT="${K8S_LOAD_ENDPOINT:-/health}"
REQUESTS="${K8S_LOAD_REQUESTS:-120}"
MAX_ERROR_RATE_PCT="${K8S_LOAD_MAX_ERROR_RATE_PCT:-1.00}"
ARTIFACT_DIR="${K8S_TEST_ARTIFACT_DIR:-artifacts/k8s-tests}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

if ! [[ "${REQUESTS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "K8S_LOAD_REQUESTS must be a positive integer, got '${REQUESTS}'." >&2
  exit 1
fi

mkdir -p "${ARTIFACT_DIR}"
RAW_FILE="${ARTIFACT_DIR}/k8s-load-raw-${TIMESTAMP}.txt"
REPORT_FILE="${ARTIFACT_DIR}/k8s-load-report-${TIMESTAMP}.md"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required but was not found in PATH." >&2
  exit 1
fi

PF_PID=""
cleanup() {
  if [[ -n "${PF_PID}" ]] && kill -0 "${PF_PID}" >/dev/null 2>&1; then
    kill "${PF_PID}" >/dev/null 2>&1 || true
    wait "${PF_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [[ -z "${K8S_TARGET_URL:-}" ]]; then
  PORT_FORWARD_LOG="/tmp/k8s-load-port-forward.log"
  kubectl -n "${NAMESPACE}" port-forward "svc/${SERVICE_NAME}" "${LOCAL_PORT}:80" >"${PORT_FORWARD_LOG}" 2>&1 &
  PF_PID=$!
  PF_READY=0
  for _ in $(seq 1 20); do
    if curl --connect-timeout 3 --max-time 5 -fsS "${BASE_URL}${LOAD_ENDPOINT}" >/dev/null 2>&1; then
      PF_READY=1
      break
    fi
    sleep 1
  done
  if [[ "${PF_READY}" -ne 1 ]]; then
    echo "Load test failed: endpoint not reachable at ${BASE_URL}${LOAD_ENDPOINT} after port-forward wait." >&2
    if [[ -f "${PORT_FORWARD_LOG}" ]]; then
      sed 's/^/  /' "${PORT_FORWARD_LOG}" >&2 || cat "${PORT_FORWARD_LOG}" >&2
    fi
    exit 1
  fi
fi

start_ns="$(date +%s%N)"
for _ in $(seq 1 "${REQUESTS}"); do
  RESULT="$(curl --connect-timeout 3 --max-time 10 -sS -o /dev/null -w '%{http_code} %{time_total}' "${BASE_URL}${LOAD_ENDPOINT}" || echo '000 10')"
  CODE="$(awk '{print $1}' <<< "${RESULT}")"
  TIME_S="$(awk '{print $2}' <<< "${RESULT}")"
  LAT_MS="$(awk -v t="${TIME_S}" 'BEGIN { printf "%.3f", t * 1000 }')"
  echo "${LAT_MS} ${CODE}" >> "${RAW_FILE}"
done
end_ns="$(date +%s%N)"

DURATION_S="$(awk -v s="${start_ns}" -v e="${end_ns}" 'BEGIN { printf "%.3f", (e-s)/1000000000 }')"
SUCCESS_COUNT="$(awk '$2 == 200 {c++} END {print c+0}' "${RAW_FILE}")"
ERROR_COUNT="$((REQUESTS - SUCCESS_COUNT))"
ERROR_RATE_PCT="$(awk -v e="${ERROR_COUNT}" -v t="${REQUESTS}" 'BEGIN { printf "%.2f", (e/t)*100 }')"
THROUGHPUT_RPS="$(awk -v t="${REQUESTS}" -v d="${DURATION_S}" 'BEGIN { if (d==0) d=1; printf "%.2f", t/d }')"
P95_INDEX="$(( (95 * REQUESTS + 99) / 100 ))"
P95_MS="$(awk -v idx="${P95_INDEX}" 'NR==idx {print $1; exit}' <(sort -n "${RAW_FILE}"))"
if [[ -z "${P95_MS}" ]]; then
  P95_MS="0.000"
fi

cat > "${REPORT_FILE}" <<EOF
# K8s Load Test Report

- timestamp: ${TIMESTAMP}
- namespace: ${NAMESPACE}
- service: ${SERVICE_NAME}
- target: ${BASE_URL}${LOAD_ENDPOINT}
- total_requests: ${REQUESTS}
- duration_seconds: ${DURATION_S}
- throughput_rps: ${THROUGHPUT_RPS}
- p95_latency_ms: ${P95_MS}
- error_rate_pct: ${ERROR_RATE_PCT}
- success_count: ${SUCCESS_COUNT}
- error_count: ${ERROR_COUNT}
EOF

cp "${REPORT_FILE}" "${ARTIFACT_DIR}/k8s-load-report-latest.md"

if awk -v e="${ERROR_RATE_PCT}" -v m="${MAX_ERROR_RATE_PCT}" 'BEGIN { exit !(e > m) }'; then
  echo "Load test failed: error_rate_pct=${ERROR_RATE_PCT} exceeded max_error_rate_pct=${MAX_ERROR_RATE_PCT}" >&2
  exit 1
fi

echo "Load test complete."
echo "throughput_rps=${THROUGHPUT_RPS} p95_latency_ms=${P95_MS} error_rate_pct=${ERROR_RATE_PCT}"
echo "Report: ${REPORT_FILE}"
