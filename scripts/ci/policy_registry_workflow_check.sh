#!/usr/bin/env bash
set -euo pipefail

require_parameterized_query() {
  local workflow_path="$1"
  local node_name="$2"
  shift 2

  local query
  local query_replacement
  query="$(jq -r --arg node_name "$node_name" '.nodes[] | select(.name == $node_name) | .parameters.query' "$workflow_path")"
  query_replacement="$(jq -r --arg node_name "$node_name" '.nodes[] | select(.name == $node_name) | .parameters.additionalFields.queryReplacement' "$workflow_path")"

  if [[ -z "$query" || "$query" == "null" ]]; then
    echo "Query not found for '${node_name}' in ${workflow_path}" >&2
    exit 1
  fi

  if grep -Fq "{{" <<<"$query"; then
    echo "Raw SQL interpolation detected in '${node_name}' for ${workflow_path}" >&2
    exit 1
  fi

  if [[ -z "$query_replacement" || "$query_replacement" == "null" ]]; then
    echo "Missing queryReplacement for '${node_name}' in ${workflow_path}" >&2
    exit 1
  fi

  for pattern in "$@"; do
    if ! grep -Fq "$pattern" <<<"$query"; then
      echo "Missing '${pattern}' in '${node_name}' query for ${workflow_path}" >&2
      exit 1
    fi
  done
}

check_policy_registry_workflows() {
  local workflow_path="n8n/workflows-v3/$1"

  if [[ ! -f "$workflow_path" ]]; then
    echo "Workflow file not found: ${workflow_path}" >&2
    exit 1
  fi

  case "$1" in
    06_policy_registry_upsert.json)
      require_parameterized_query "$workflow_path" "Upsert Workflow Rule" '$1' '$2' '$3' '$4' '$5::jsonb' '$6'
      require_parameterized_query "$workflow_path" "Insert Upsert Log" '$1' '$2::jsonb'
      ;;
    07_policy_registry_publish.json)
      require_parameterized_query "$workflow_path" "Publish Revision" '$1' '$2' '$3' '$1'
      require_parameterized_query "$workflow_path" "Insert Publish Log" '$1' '$2' '$3::jsonb'
      require_parameterized_query "$workflow_path" "Load Published Payload" '$1'
      ;;
    09_policy_registry_get.json)
      require_parameterized_query "$workflow_path" "Get Workflow Rule" '$1' '$2'
      ;;
    11_policy_candidate_seed.json)
      require_parameterized_query "$workflow_path" "Insert Seed Episode" '$1' '$2' '$3' '$4'
      ;;
    12_policy_registry_delete.json)
      require_parameterized_query "$workflow_path" "Delete Workflow Rule" '$1' '$2' '$3' '$4'
      require_parameterized_query "$workflow_path" "Insert Delete Log" '$1' '$2::jsonb'
      ;;
    *)
      echo "Unhandled workflow fixture: $1" >&2
      exit 1
      ;;
  esac
}

check_policy_registry_workflows "06_policy_registry_upsert.json"
check_policy_registry_workflows "07_policy_registry_publish.json"
check_policy_registry_workflows "09_policy_registry_get.json"
check_policy_registry_workflows "11_policy_candidate_seed.json"
check_policy_registry_workflows "12_policy_registry_delete.json"

echo "Policy registry workflow SQL checks passed."
