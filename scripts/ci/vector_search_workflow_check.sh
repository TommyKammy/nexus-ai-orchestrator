#!/usr/bin/env bash
set -euo pipefail

search_patterns=(
  'ORDER BY embedding <=> $1::vector'
  'LIMIT $4;'
)

response_patterns=(
  "rank: index + 1"
  "similarity_score"
  "results_count: rankedResults.length"
)

check_workflow() {
  local workflow_path="$1"
  local search_query
  local search_replacement
  local audit_query
  local audit_replacement
  local response_code

  search_query="$(jq -r '.nodes[] | select(.name == "Search Vectors") | .parameters.query' "$workflow_path")"
  search_replacement="$(jq -r '.nodes[] | select(.name == "Search Vectors") | .parameters.additionalFields.queryReplacement' "$workflow_path")"
  audit_query="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.query' "$workflow_path")"
  audit_replacement="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.additionalFields.queryReplacement' "$workflow_path")"
  response_code="$(jq -r '.nodes[] | select(.name == "Success Response") | .parameters.jsCode' "$workflow_path")"

  for pattern in "${search_patterns[@]}"; do
    if ! grep -Fq "$pattern" <<< "$search_query"; then
      echo "Missing '${pattern}' in Search Vectors query for ${workflow_path}" >&2
      exit 1
    fi
  done

  if [[ -z "$search_replacement" || "$search_replacement" == "null" ]]; then
    echo "Missing Search Vectors queryReplacement for ${workflow_path}" >&2
    exit 1
  fi

  if ! grep -Fq '$1' <<< "$audit_query"; then
    echo "Insert Audit query must use parameter binding in ${workflow_path}" >&2
    exit 1
  fi
  if [[ -z "$audit_replacement" || "$audit_replacement" == "null" ]]; then
    echo "Missing Insert Audit queryReplacement for ${workflow_path}" >&2
    exit 1
  fi

  for pattern in "${response_patterns[@]}"; do
    if ! grep -Fq "$pattern" <<< "$response_code"; then
      echo "Missing '${pattern}' in Success Response for ${workflow_path}" >&2
      exit 1
    fi
  done
}

check_workflow "n8n/workflows/02_vector_search.json"
check_workflow "n8n/workflows-v3/02_vector_search.json"

echo "Vector search workflow ranking checks passed."
