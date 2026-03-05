#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

command -v docker >/dev/null 2>&1 || {
  echo "docker is required for secret scan" >&2
  exit 1
}
command -v jq >/dev/null 2>&1 || {
  echo "jq is required for secret scan" >&2
  exit 1
}

ARTIFACT_DIR="${ROOT_DIR}/artifacts/security"
REPORT_PATH="${ARTIFACT_DIR}/secret-scan-report.json"
REPORT_PATH_IN_CONTAINER="artifacts/security/secret-scan-report.json"
mkdir -p "${ARTIFACT_DIR}"

docker run --rm -v "${ROOT_DIR}:/workspace" -w /workspace aquasec/trivy:0.61.0 fs \
  --scanners secret \
  --severity HIGH,CRITICAL \
  --format json \
  --output "${REPORT_PATH_IN_CONTAINER}" \
  --exit-code 0 \
  --skip-dirs artifacts \
  --skip-dirs caddy_data \
  --skip-dirs caddy_config \
  --skip-dirs logs \
  --skip-dirs postgres \
  --skip-dirs redis \
  --skip-dirs n8n \
  .

critical_count="$(jq '[((.Results // [])[]?.Secrets // [])[]? | select(.Severity=="CRITICAL")] | length' "${REPORT_PATH}")"
high_count="$(jq '[((.Results // [])[]?.Secrets // [])[]? | select(.Severity=="HIGH")] | length' "${REPORT_PATH}")"

echo "secret scan summary: CRITICAL=${critical_count} HIGH=${high_count}"

if [[ "${critical_count}" -gt 0 || "${high_count}" -gt 0 ]]; then
  echo "Secret scan failed: high/critical findings detected." >&2
  jq -r '((.Results // [])[]?.Secrets // [])[]? | select(.Severity=="CRITICAL" or .Severity=="HIGH") | "- [\(.Severity)] \(.RuleID) in \(.Target)"' "${REPORT_PATH}" >&2
  exit 1
fi
