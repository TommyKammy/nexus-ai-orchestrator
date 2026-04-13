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
  local continue_on_fail
  local parse_to_search
  local parse_to_audit
  local search_to_audit
  local search_query
  local search_url
  local search_headers
  local search_body
  local search_replacement
  local audit_query
  local audit_url
  local audit_headers
  local audit_body
  local audit_replacement
  local response_code
  local is_service_boundary

  for node_name in "${required_nodes[@]}"; do
    if ! jq -e --arg node_name "$node_name" '.nodes[] | select(.name == $node_name)' "$workflow_path" >/dev/null; then
      echo "Missing required node '$node_name' in ${workflow_path}" >&2
      exit 1
    fi
  done

  policy_url="$(jq -r '.nodes[] | select(.name == "Evaluate Policy") | .parameters.url' "$workflow_path")"
  check_policy_code="$(jq -r '.nodes[] | select(.name == "Check Policy") | .parameters.jsCode' "$workflow_path")"
  continue_on_fail="$(jq -r '.nodes[] | select(.name == "Evaluate Policy") | (.continueOnFail // false)' "$workflow_path")"
  validation_true_target="$(jq -r '.connections["Validation Error?"].main[0][0].node // empty' "$workflow_path")"
  validation_false_target="$(jq -r '.connections["Validation Error?"].main[1][0].node // empty' "$workflow_path")"
  policy_true_target="$(jq -r '.connections["Policy Error?"].main[0][0].node // empty' "$workflow_path")"
  policy_false_target="$(jq -r '.connections["Policy Error?"].main[1][0].node // empty' "$workflow_path")"
  parse_to_search="$(jq -r '.connections["Parse Embedding"].main[0] | any(.node == "Search Vectors")' "$workflow_path")"
  parse_to_audit="$(jq -r '.connections["Parse Embedding"].main[0] | any(.node == "Insert Audit")' "$workflow_path")"
  search_to_audit="$(jq -r '.connections["Search Vectors"].main[0] | any(.node == "Insert Audit")' "$workflow_path")"
  is_service_boundary="$(jq -r '.nodes[] | select(.name == "Search Vectors") | .type == "n8n-nodes-base.httpRequest"' "$workflow_path")"
  search_query="$(jq -r '.nodes[] | select(.name == "Search Vectors") | .parameters.query' "$workflow_path")"
  search_url="$(jq -r '.nodes[] | select(.name == "Search Vectors") | .parameters.url' "$workflow_path")"
  search_headers="$(jq -c '.nodes[] | select(.name == "Search Vectors") | .parameters.headerParameters.parameters // []' "$workflow_path")"
  search_body="$(jq -r '.nodes[] | select(.name == "Search Vectors") | .parameters.jsonBody' "$workflow_path")"
  search_replacement="$(jq -r '.nodes[] | select(.name == "Search Vectors") | .parameters.additionalFields.queryReplacement' "$workflow_path")"
  audit_query="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.query' "$workflow_path")"
  audit_url="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.url' "$workflow_path")"
  audit_headers="$(jq -c '.nodes[] | select(.name == "Insert Audit") | .parameters.headerParameters.parameters // []' "$workflow_path")"
  audit_body="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.jsonBody' "$workflow_path")"
  audit_replacement="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.additionalFields.queryReplacement' "$workflow_path")"
  response_code="$(jq -r '.nodes[] | select(.name == "Success Response") | .parameters.jsCode' "$workflow_path")"

  if [[ "$policy_url" != "http://opa:8181/v1/data/ai/policy/result" ]]; then
    echo "Policy URL mismatch in ${workflow_path}" >&2
    exit 1
  fi

  if [[ "$continue_on_fail" != "true" ]]; then
    echo "Evaluate Policy must continue on fail in ${workflow_path}" >&2
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

  if [[ "$parse_to_search" != "true" || "$parse_to_audit" != "true" || "$search_to_audit" != "false" ]]; then
    echo "Vector search audit flow must branch from Parse Embedding and not fan out from Search Vectors in ${workflow_path}" >&2
    exit 1
  fi

  for pattern in "invalid_policy_response" "Policy requires approval" "Policy denied"; do
    if ! grep -Fq "$pattern" <<< "$check_policy_code"; then
      echo "Missing '${pattern}' in Check Policy for ${workflow_path}" >&2
      exit 1
    fi
  done

  if [[ "$is_service_boundary" == "true" ]]; then
    if [[ "$search_url" != "http://policy-bundle-server:8088/internal/tenant-data/memory/search" ]]; then
      echo "Search Vectors must call the memory search service in ${workflow_path}" >&2
      exit 1
    fi
    if ! grep -Fq "X-Authenticated-Tenant-Id" <<<"$search_headers"; then
      echo "Search Vectors must forward X-Authenticated-Tenant-Id in ${workflow_path}" >&2
      exit 1
    fi
    for pattern in "embedding" "tenant_id" "scope"; do
      if ! grep -Fq "$pattern" <<<"$search_body"; then
        echo "Search Vectors request body is missing '${pattern}' in ${workflow_path}" >&2
        exit 1
      fi
    done

    if [[ "$audit_url" != "http://policy-bundle-server:8088/internal/tenant-data/audit/event" ]]; then
      echo "Insert Audit must call the audit service in ${workflow_path}" >&2
      exit 1
    fi
    if ! grep -Fq "X-Authenticated-Tenant-Id" <<<"$audit_headers"; then
      echo "Insert Audit must forward X-Authenticated-Tenant-Id in ${workflow_path}" >&2
      exit 1
    fi
    for pattern in "tenant_id" "policy" "request_id"; do
      if ! grep -Fq "$pattern" <<<"$audit_body"; then
        echo "Insert Audit request body is missing '${pattern}' in ${workflow_path}" >&2
        exit 1
      fi
    done
  else
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
