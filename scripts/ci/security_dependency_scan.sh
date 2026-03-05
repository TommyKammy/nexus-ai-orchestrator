#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

command -v docker >/dev/null 2>&1 || {
  echo "docker is required for dependency vulnerability scan" >&2
  exit 1
}
command -v jq >/dev/null 2>&1 || {
  echo "jq is required for dependency vulnerability scan" >&2
  exit 1
}

ARTIFACT_DIR="${ROOT_DIR}/artifacts/security"
REPORT_PATH="${ARTIFACT_DIR}/dependency-vuln-report.json"
REPORT_PATH_IN_CONTAINER="artifacts/security/dependency-vuln-report.json"
mkdir -p "${ARTIFACT_DIR}"

# Keep scan focused on source/config artifacts and avoid runtime data directories.
docker run --rm -v "${ROOT_DIR}:/workspace" -w /workspace aquasec/trivy:0.61.0 fs \
  --scanners vuln \
  --severity MEDIUM,HIGH,CRITICAL \
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

critical_count="$(jq '[((.Results // [])[]?.Vulnerabilities // [])[]? | select(.Severity=="CRITICAL")] | length' "${REPORT_PATH}")"
high_count="$(jq '[((.Results // [])[]?.Vulnerabilities // [])[]? | select(.Severity=="HIGH")] | length' "${REPORT_PATH}")"
medium_count="$(jq '[((.Results // [])[]?.Vulnerabilities // [])[]? | select(.Severity=="MEDIUM")] | length' "${REPORT_PATH}")"

echo "dependency scan summary: CRITICAL=${critical_count} HIGH=${high_count} MEDIUM=${medium_count}"

if [[ "${critical_count}" -gt 0 || "${high_count}" -gt 0 ]]; then
  echo "Dependency scan failed: high/critical vulnerabilities detected." >&2
  jq -r '((.Results // [])[]?.Vulnerabilities // [])[]? | select(.Severity=="CRITICAL" or .Severity=="HIGH") | "- [\(.Severity)] \(.PkgName) \(.InstalledVersion) \(.VulnerabilityID) (fixed: \(.FixedVersion // "n/a"))"' "${REPORT_PATH}" >&2
  exit 1
fi
