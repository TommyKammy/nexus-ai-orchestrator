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
  "Insert Audit"
  "Success Response"
)

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
  "policy:"
)

check_workflow() {
  local workflow_path="$1"
  local policy_url
  local check_policy_code
  local continue_on_fail
  local validation_true_target
  local validation_false_target
  local policy_true_target
  local policy_false_target
  local query
  local audit_url
  local audit_headers
  local audit_body
  local query_replacement
  local response_json
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
  is_service_boundary="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .type == "n8n-nodes-base.httpRequest"' "$workflow_path")"
  query="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.query' "$workflow_path")"
  audit_url="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.url' "$workflow_path")"
  audit_headers="$(jq -c '.nodes[] | select(.name == "Insert Audit") | .parameters.headerParameters.parameters // []' "$workflow_path")"
  audit_body="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.jsonBody' "$workflow_path")"
  query_replacement="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.additionalFields.queryReplacement' "$workflow_path")"
  response_json="$(jq -r '.nodes[] | select(.name == "Success Response") | .parameters.json' "$workflow_path")"

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

  if [[ "$policy_true_target" != "Error Response" || "$policy_false_target" != "Insert Audit" ]]; then
    echo "Policy Error? node must route true->Error Response and false->Insert Audit in ${workflow_path}" >&2
    exit 1
  fi

  for pattern in "invalid_policy_response" "Policy requires approval" "Policy denied"; do
    if ! grep -Fq "$pattern" <<< "$check_policy_code"; then
      echo "Missing '${pattern}' in Check Policy for ${workflow_path}" >&2
      exit 1
    fi
  done

  if [[ "$is_service_boundary" == "true" ]]; then
    if [[ "$audit_url" != "http://policy-bundle-server:8088/internal/tenant-data/audit/event" ]]; then
      echo "Insert Audit must call the audit service in ${workflow_path}" >&2
      exit 1
    fi
    if ! grep -Fq "X-Authenticated-Tenant-Id" <<<"$audit_headers"; then
      echo "Insert Audit must forward X-Authenticated-Tenant-Id in ${workflow_path}" >&2
      exit 1
    fi
    if ! grep -Fq "X-API-Key" <<<"$audit_headers"; then
      echo "Insert Audit must forward X-API-Key in ${workflow_path}" >&2
      exit 1
    fi
    for pattern in "payload_jsonb" "request_id" "policy_id" "policy_version" "risk_score"; do
      if ! grep -Fq "$pattern" <<<"$audit_body"; then
        echo "Insert Audit request body is missing '${pattern}' in ${workflow_path}" >&2
        exit 1
      fi
    done
  else
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

echo "Audit append workflow policy-gate checks passed."
