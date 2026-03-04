#!/usr/bin/env bash
set -euo pipefail

required_patterns=(
  "content_hash"
  "metadata_jsonb"
  "ON CONFLICT (tenant_id, scope, content_hash)"
  "RETURNING id, content_hash;"
)

check_workflow() {
  local workflow_path="$1"
  local query
  query="$(jq -r '.nodes[] | select(.name == "Insert Vector") | .parameters.query' "$workflow_path")"

  if [[ -z "$query" || "$query" == "null" ]]; then
    echo "Insert Vector query not found: ${workflow_path}" >&2
    exit 1
  fi

  for pattern in "${required_patterns[@]}"; do
    if ! grep -Fq "$pattern" <<< "$query"; then
      echo "Missing '${pattern}' in ${workflow_path}" >&2
      exit 1
    fi
  done
}

check_workflow "n8n/workflows/01_memory_ingest.json"
check_workflow "n8n/workflows-v3/01_memory_ingest.json"

echo "Memory ingest workflow metadata checks passed."
