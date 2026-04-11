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
insert_query="$(jq -r '.nodes[] | select(.name == "Insert Approval Audit") | .parameters.query' "$workflow_path")"
insert_replacement="$(jq -r '.nodes[] | select(.name == "Insert Approval Audit") | .parameters.additionalFields.queryReplacement' "$workflow_path")"
success_json="$(jq -r '.nodes[] | select(.name == "Success Response") | .parameters.json' "$workflow_path")"

for pattern in "approval.token" "timingSafeEqual" "N8N_ENCRYPTION_KEY" "policy.decision must be requires_approval"; do
  if ! grep -Fq "$pattern" <<<"$validate_code"; then
    echo "Missing '${pattern}' in Validate Approval for ${workflow_path}" >&2
    exit 1
  fi
done

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

for pattern in '$('\'Validate Approval\'').first().json' "decision:" "approver:" "policy:"; do
  if ! grep -Fq "$pattern" <<<"$success_json"; then
    echo "Missing '${pattern}' in Success Response for ${workflow_path}" >&2
    exit 1
  fi
done

echo "Policy approval workflow checks passed."
