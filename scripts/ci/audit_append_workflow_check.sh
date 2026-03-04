#!/usr/bin/env bash
set -euo pipefail

query_patterns=(
  "request_id"
  "policy_id"
  "policy_version"
  "risk_score"
  "RETURNING id, request_id, created_at;"
  '$1'
  '$2'
  '$3'
  '$4'
  '$5'
  '$6'
  '$7'
  '$8'
  '$9'
  '$10'
)

response_patterns=(
  "audit_event_id"
  "request_id"
  "created_at"
)

check_workflow() {
  local workflow_path="$1"
  local query
  local query_replacement
  local response_json

  query="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.query' "$workflow_path")"
  query_replacement="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.additionalFields.queryReplacement' "$workflow_path")"
  response_json="$(jq -r '.nodes[] | select(.name == "Success Response") | .parameters.json' "$workflow_path")"

  for pattern in "${query_patterns[@]}"; do
    if ! grep -Fq "$pattern" <<< "$query"; then
      echo "Missing '${pattern}' in Insert Audit query for ${workflow_path}" >&2
      exit 1
    fi
  done

  if [[ -z "$query_replacement" || "$query_replacement" == "null" ]]; then
    echo "Missing Insert Audit queryReplacement for ${workflow_path}" >&2
    exit 1
  fi

  for pattern in "${response_patterns[@]}"; do
    if ! grep -Fq "$pattern" <<< "$response_json"; then
      echo "Missing '${pattern}' in Success Response json for ${workflow_path}" >&2
      exit 1
    fi
  done
}

check_workflow "n8n/workflows/03_audit_append.json"
check_workflow "n8n/workflows-v3/03_audit_append.json"

echo "Audit append workflow persistence checks passed."
