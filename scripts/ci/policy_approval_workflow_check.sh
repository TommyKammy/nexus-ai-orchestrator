#!/usr/bin/env bash
set -euo pipefail

workflow_path="n8n/workflows-v3/05_policy_approval.json"

required_nodes=(
  "Webhook"
  "Check Webhook Auth"
  "Webhook Authorized?"
  "Unauthorized Response"
  "Validate Approval"
  "Prepare Audit"
  "Error Response"
  "Insert Approval Audit"
  "Success Response"
)

for node_name in "${required_nodes[@]}"; do
  if ! jq -e --arg node_name "$node_name" '.nodes[] | select(.name == $node_name)' "$workflow_path" >/dev/null; then
    echo "Missing required node '$node_name' in ${workflow_path}" >&2
    exit 1
  fi
done

validate_code="$(jq -r '.nodes[] | select(.name == "Validate Approval") | .parameters.jsCode' "$workflow_path")"
insert_node_is_service_boundary="$(jq -r '.nodes[] | select(.name == "Insert Approval Audit") | .type == "n8n-nodes-base.httpRequest"' "$workflow_path")"
insert_method="$(jq -r '.nodes[] | select(.name == "Insert Approval Audit") | .parameters.method' "$workflow_path")"
insert_query="$(jq -r '.nodes[] | select(.name == "Insert Approval Audit") | .parameters.query' "$workflow_path")"
insert_url="$(jq -r '.nodes[] | select(.name == "Insert Approval Audit") | .parameters.url' "$workflow_path")"
insert_headers="$(jq -c '.nodes[] | select(.name == "Insert Approval Audit") | .parameters.headerParameters.parameters // []' "$workflow_path")"
insert_body="$(jq -r '.nodes[] | select(.name == "Insert Approval Audit") | .parameters.jsonBody' "$workflow_path")"
insert_replacement="$(jq -r '.nodes[] | select(.name == "Insert Approval Audit") | .parameters.additionalFields.queryReplacement' "$workflow_path")"
success_json="$(jq -r '.nodes[] | select(.name == "Success Response") | .parameters.json' "$workflow_path")"

for pattern in "approval.token" "timingSafeEqual" "N8N_ENCRYPTION_KEY" "policy.decision must be requires_approval"; do
  if ! grep -Fq "$pattern" <<<"$validate_code"; then
    echo "Missing '${pattern}' in Validate Approval for ${workflow_path}" >&2
    exit 1
  fi
done

if [[ "$insert_node_is_service_boundary" == "true" ]]; then
  if [[ "$insert_method" != "POST" ]]; then
    echo "Insert Approval Audit must use POST in ${workflow_path}" >&2
    exit 1
  fi
  if [[ "$insert_url" != "http://policy-bundle-server:8088/internal/tenant-data/audit/event" ]]; then
    echo "Insert Approval Audit must call the internal audit service in ${workflow_path}" >&2
    exit 1
  fi
  if ! grep -Fq "X-API-Key" <<<"$insert_headers"; then
    echo "Insert Approval Audit must forward X-API-Key in ${workflow_path}" >&2
    exit 1
  fi
  if ! grep -Fq "POLICY_BUNDLE_INTERNAL_API_KEY" <<<"$insert_headers"; then
    echo "Insert Approval Audit must source X-API-Key from workflow environment in ${workflow_path}" >&2
    exit 1
  fi
  for pattern in "actor" "action" "target" "decision" "payload_jsonb" "request_id" "policy_id" "policy_version" "risk_score" "approval" "policy"; do
    if ! grep -Fq "$pattern" <<<"$insert_body"; then
      echo "Insert Approval Audit request body is missing '${pattern}' in ${workflow_path}" >&2
      exit 1
    fi
  done
else
  for pattern in '$1' '$9' 'RETURNING id, request_id, created_at;'; do
    if ! grep -Fq "$pattern" <<<"$insert_query"; then
      echo "Insert Approval Audit query must remain parameterized in ${workflow_path}" >&2
      exit 1
    fi
  done

  if [[ -z "$insert_replacement" || "$insert_replacement" == "null" ]]; then
    echo "Missing Insert Approval Audit queryReplacement for ${workflow_path}" >&2
    exit 1
  fi
fi

for pattern in '$('\'Validate Approval\'').first().json' "decision:" "approver:" "policy:"; do
  if ! grep -Fq "$pattern" <<<"$success_json"; then
    echo "Missing '${pattern}' in Success Response for ${workflow_path}" >&2
    exit 1
  fi
done

echo "Policy approval workflow checks passed."
