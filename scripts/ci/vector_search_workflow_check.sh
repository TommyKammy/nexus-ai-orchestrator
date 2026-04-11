#!/usr/bin/env bash
set -euo pipefail

required_nodes=(
  "Webhook"
  "Validate Input"
  "Check Validation"
  "Validation Error?"
  "Evaluate Policy"
  "Check Policy"
  "Policy Error?"
  "Error Response"
  "Generate Query Embedding"
  "Parse Embedding"
  "Search Vectors"
  "Insert Audit"
  "Success Response"
)

search_patterns=(
  'ORDER BY embedding <=> $1::vector'
  'LIMIT $4'
)

response_patterns=(
  "rank:"
  "similarity_score"
  "results_count:"
  "policy:"
)

check_workflow() {
  local workflow_path="$1"
  local policy_url
  local check_policy_code
  local validation_true_target
  local validation_false_target
  local policy_true_target
  local policy_false_target
  local search_query
  local search_replacement
  local audit_query
  local audit_replacement
  local response_code

  for node_name in "${required_nodes[@]}"; do
    if ! jq -e --arg node_name "$node_name" '.nodes[] | select(.name == $node_name)' "$workflow_path" >/dev/null; then
      echo "Missing required node '$node_name' in ${workflow_path}" >&2
      exit 1
    fi
  done

  policy_url="$(jq -r '.nodes[] | select(.name == "Evaluate Policy") | .parameters.url' "$workflow_path")"
  check_policy_code="$(jq -r '.nodes[] | select(.name == "Check Policy") | .parameters.jsCode' "$workflow_path")"
  validation_true_target="$(jq -r '.connections["Validation Error?"].main[0][0].node // empty' "$workflow_path")"
  validation_false_target="$(jq -r '.connections["Validation Error?"].main[1][0].node // empty' "$workflow_path")"
  policy_true_target="$(jq -r '.connections["Policy Error?"].main[0][0].node // empty' "$workflow_path")"
  policy_false_target="$(jq -r '.connections["Policy Error?"].main[1][0].node // empty' "$workflow_path")"
  search_query="$(jq -r '.nodes[] | select(.name == "Search Vectors") | .parameters.query' "$workflow_path")"
  search_replacement="$(jq -r '.nodes[] | select(.name == "Search Vectors") | .parameters.additionalFields.queryReplacement' "$workflow_path")"
  audit_query="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.query' "$workflow_path")"
  audit_replacement="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.additionalFields.queryReplacement' "$workflow_path")"
  response_code="$(jq -r '.nodes[] | select(.name == "Success Response") | .parameters.jsCode' "$workflow_path")"

  if [[ "$policy_url" != "http://opa:8181/v1/data/ai/policy/result" ]]; then
    echo "Policy URL mismatch in ${workflow_path}" >&2
    exit 1
  fi

  if [[ "$validation_true_target" != "Error Response" || "$validation_false_target" != "Evaluate Policy" ]]; then
    echo "Validation Error? node must route true->Error Response and false->Evaluate Policy in ${workflow_path}" >&2
    exit 1
  fi

  if [[ "$policy_true_target" != "Error Response" || "$policy_false_target" != "Generate Query Embedding" ]]; then
    echo "Policy Error? node must route true->Error Response and false->Generate Query Embedding in ${workflow_path}" >&2
    exit 1
  fi

  for pattern in "invalid_policy_response" "Policy requires approval" "Policy denied"; do
    if ! grep -Fq "$pattern" <<< "$check_policy_code"; then
      echo "Missing '${pattern}' in Check Policy for ${workflow_path}" >&2
      exit 1
    fi
  done

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

  for pattern in '$1' '$8'; do
    if ! grep -Fq "$pattern" <<< "$audit_query"; then
      echo "Insert Audit query must remain parameterized in ${workflow_path}" >&2
      exit 1
    fi
  done
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

echo "Vector search workflow policy-gate checks passed."
