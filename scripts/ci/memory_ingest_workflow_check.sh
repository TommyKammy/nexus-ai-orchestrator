#!/usr/bin/env bash
set -euo pipefail

required_patterns=(
  "content_hash"
  "metadata_jsonb"
  "tags"
  "source"
  "ON CONFLICT (tenant_id, scope, content_hash)"
  "WHERE content_hash IS NOT NULL"
  "RETURNING id, content_hash"
  '$1'
  '$2'
  '$3'
)

check_workflow() {
  local workflow_path="$1"
  local query
  local query_replacement
  query="$(jq -r '.nodes[] | select(.name == "Insert Vector") | .parameters.query' "$workflow_path")"
  query_replacement="$(jq -r '.nodes[] | select(.name == "Insert Vector") | .parameters.additionalFields.queryReplacement' "$workflow_path")"

  if [[ -z "$query" || "$query" == "null" ]]; then
    echo "Insert Vector query not found: ${workflow_path}" >&2
    exit 1
  fi
  if [[ -z "$query_replacement" || "$query_replacement" == "null" ]]; then
    echo "Insert Vector queryReplacement not found: ${workflow_path}" >&2
    exit 1
  fi

  for pattern in "${required_patterns[@]}"; do
    if ! grep -Fq "$pattern" <<< "$query"; then
      echo "Missing '${pattern}' in ${workflow_path}" >&2
      exit 1
    fi
  done
  if ! grep -Fq "content_hash" <<< "$query_replacement"; then
    echo "Missing 'content_hash' in queryReplacement for ${workflow_path}" >&2
    exit 1
  fi
}

check_workflow "n8n/workflows/01_memory_ingest.json"
check_workflow "n8n/workflows-v3/01_memory_ingest.json"

echo "Memory ingest workflow metadata checks passed."
