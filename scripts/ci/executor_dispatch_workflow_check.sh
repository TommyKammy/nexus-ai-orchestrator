#!/usr/bin/env bash
set -euo pipefail

required_nodes=(
  "Webhook"
  "Validate and Execute"
  "Check Validation"
  "Validation Error?"
  "Evaluate Policy"
  "Check Policy"
  "Policy Error?"
  "Error Response"
  "Finalize Success Payload"
  "Insert Episode"
  "Insert Audit"
  "Success Response"
)

check_workflow() {
  local workflow_path="$1"
  local workflow_dir
  local webhook_path
  local policy_url
  local episode_query
  local episode_url
  local episode_headers
  local episode_body
  local episode_replacement
  local audit_query
  local audit_url
  local audit_headers
  local audit_body
  local audit_replacement
  local success_response
  local validation_true_target
  local validation_false_target
  local brain_workflow_id
  local brain_workflow_file
  local is_service_boundary

  workflow_dir="$(dirname "$workflow_path")"
  webhook_path="$(jq -r '.nodes[] | select(.name == "Webhook") | .parameters.path' "$workflow_path")"
  policy_url="$(jq -r '.nodes[] | select(.name == "Evaluate Policy") | .parameters.url' "$workflow_path")"
  is_service_boundary="$(jq -r '.nodes[] | select(.name == "Insert Episode") | .type == "n8n-nodes-base.httpRequest"' "$workflow_path")"
  episode_query="$(jq -r '.nodes[] | select(.name == "Insert Episode") | .parameters.query' "$workflow_path")"
  episode_url="$(jq -r '.nodes[] | select(.name == "Insert Episode") | .parameters.url' "$workflow_path")"
  episode_headers="$(jq -c '.nodes[] | select(.name == "Insert Episode") | .parameters.headerParameters.parameters // []' "$workflow_path")"
  episode_body="$(jq -r '.nodes[] | select(.name == "Insert Episode") | .parameters.jsonBody' "$workflow_path")"
  episode_replacement="$(jq -r '.nodes[] | select(.name == "Insert Episode") | .parameters.additionalFields.queryReplacement' "$workflow_path")"
  audit_query="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.query' "$workflow_path")"
  audit_url="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.url' "$workflow_path")"
  audit_headers="$(jq -c '.nodes[] | select(.name == "Insert Audit") | .parameters.headerParameters.parameters // []' "$workflow_path")"
  audit_body="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.jsonBody' "$workflow_path")"
  audit_replacement="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.additionalFields.queryReplacement' "$workflow_path")"
  success_response="$(jq -r '.nodes[] | select(.name == "Success Response") | (.parameters.responseBody // .parameters.json // "")' "$workflow_path")"
  validation_true_target="$(jq -r '.connections["Validation Error?"].main[0][0].node // empty' "$workflow_path")"
  validation_false_target="$(jq -r '.connections["Validation Error?"].main[1][0].node // empty' "$workflow_path")"
  brain_workflow_id="$(jq -r '.nodes[] | select(.name == "Execute Brain Router") | (.parameters.workflowId.value // empty)' "$workflow_path")"
  brain_workflow_file="${workflow_dir}/${brain_workflow_id}.json"

  for node_name in "${required_nodes[@]}"; do
    if ! jq -e --arg node_name "$node_name" '.nodes[] | select(.name == $node_name)' "$workflow_path" >/dev/null; then
      echo "Missing required node '$node_name' in ${workflow_path}" >&2
      exit 1
    fi
  done

  if [[ "$webhook_path" != "executor/run" ]]; then
    echo "Webhook path must be executor/run in ${workflow_path}" >&2
    exit 1
  fi

  if [[ "$policy_url" != "http://opa:8181/v1/data/ai/policy/result" ]]; then
    echo "Policy URL mismatch in ${workflow_path}" >&2
    exit 1
  fi

  if [[ "$validation_true_target" != "Error Response" || "$validation_false_target" != "Evaluate Policy" ]]; then
    echo "Validation Error? node must route true->Error Response and false->Evaluate Policy in ${workflow_path}" >&2
    exit 1
  fi

  if [[ "$is_service_boundary" == "true" ]]; then
    if [[ "$episode_url" != "http://policy-bundle-server:8088/internal/tenant-data/memory/episode" ]]; then
      echo "Insert Episode must call the memory episode service in ${workflow_path}" >&2
      exit 1
    fi
    if ! grep -Fq "X-Authenticated-Tenant-Id" <<<"$episode_headers"; then
      echo "Insert Episode must forward X-Authenticated-Tenant-Id in ${workflow_path}" >&2
      exit 1
    fi
    if ! grep -Fq "X-API-Key" <<<"$episode_headers"; then
      echo "Insert Episode must forward X-API-Key in ${workflow_path}" >&2
      exit 1
    fi
    for pattern in "tenant_id" "scope" "outcome" "metadata_jsonb"; do
      if ! grep -Fq "$pattern" <<<"$episode_body"; then
        echo "Insert Episode request body is missing '${pattern}' in ${workflow_path}" >&2
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
    if ! grep -Fq "X-API-Key" <<<"$audit_headers"; then
      echo "Insert Audit must forward X-API-Key in ${workflow_path}" >&2
      exit 1
    fi
    for pattern in "tenant_id" "policy" "request_id"; do
      if ! grep -Fq "$pattern" <<<"$audit_body"; then
        echo "Insert Audit request body is missing '${pattern}' in ${workflow_path}" >&2
        exit 1
      fi
    done
  else
    if ! grep -Fq '$1' <<<"$episode_query" || ! grep -Fq '$4::jsonb' <<<"$episode_query"; then
      echo "Insert Episode query must be parameterized in ${workflow_path}" >&2
      exit 1
    fi
    if [[ -z "$episode_replacement" || "$episode_replacement" == "null" ]]; then
      echo "Insert Episode queryReplacement missing in ${workflow_path}" >&2
      exit 1
    fi

    if ! grep -Fq '$1' <<<"$audit_query" || ! grep -Fq '$8' <<<"$audit_query"; then
      echo "Insert Audit query must be parameterized in ${workflow_path}" >&2
      exit 1
    fi
    if [[ -z "$audit_replacement" || "$audit_replacement" == "null" ]]; then
      echo "Insert Audit queryReplacement missing in ${workflow_path}" >&2
      exit 1
    fi
  fi

  if ! grep -Fq "policy:" <<<"$success_response"; then
    echo "Success response must include policy object in ${workflow_path}" >&2
    exit 1
  fi

  if [[ -n "$brain_workflow_id" && ! -f "$brain_workflow_file" ]]; then
    echo "Missing referenced subworkflow '${brain_workflow_id}.json' for ${workflow_path}" >&2
    exit 1
  fi
}

check_workflow "n8n/workflows/04_executor_dispatch.json"
check_workflow "n8n/workflows-v3/04_executor_dispatch.json"

echo "Executor dispatch orchestration checks passed."
