#!/usr/bin/env bash
set -euo pipefail

TRIVY_IMAGE="${TRIVY_IMAGE:-aquasec/trivy:0.61.0@sha256:6967db29ce5294d054121e94b3cb1262de858af63b4547bb1bade66a4306f2e4}"

# Keep scans focused on repository source/config and avoid runtime-generated state.
TRIVY_SKIP_ARGS=(
  --skip-dirs artifacts
  --skip-dirs caddy_data
  --skip-dirs caddy_config
  --skip-dirs logs
  --skip-dirs postgres
  --skip-dirs redis
  --skip-files n8n/config
  --skip-files n8n/crash.journal
  --skip-files n8n/n8nEventLog.log
  --skip-files n8n/n8nEventLog-1.log
  --skip-files n8n/n8nEventLog-2.log
  --skip-files n8n/n8nEventLog-3.log
)

run_trivy_fs() {
  local root_dir="$1"
  shift

  docker run --rm -v "${root_dir}:/workspace" -w /workspace "${TRIVY_IMAGE}" fs \
    "$@" \
    "${TRIVY_SKIP_ARGS[@]}" \
    .
}
