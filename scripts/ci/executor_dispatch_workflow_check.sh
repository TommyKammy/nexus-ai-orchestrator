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
  local episode_replacement
  local audit_query
  local audit_replacement
  local success_response
  local validation_gate_targets
  local brain_workflow_id
  local brain_workflow_file

  workflow_dir="$(dirname "$workflow_path")"
  webhook_path="$(jq -r '.nodes[] | select(.name == "Webhook") | .parameters.path' "$workflow_path")"
  policy_url="$(jq -r '.nodes[] | select(.name == "Evaluate Policy") | .parameters.url' "$workflow_path")"
  episode_query="$(jq -r '.nodes[] | select(.name == "Insert Episode") | .parameters.query' "$workflow_path")"
  episode_replacement="$(jq -r '.nodes[] | select(.name == "Insert Episode") | .parameters.additionalFields.queryReplacement' "$workflow_path")"
  audit_query="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.query' "$workflow_path")"
  audit_replacement="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.additionalFields.queryReplacement' "$workflow_path")"
  success_response="$(jq -r '.nodes[] | select(.name == "Success Response") | (.parameters.responseBody // .parameters.json // "")' "$workflow_path")"
  validation_gate_targets="$(jq -r '.connections["Validation Error?"].main[][]?.node' "$workflow_path")"
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

  if ! grep -Fq "Error Response" <<<"$validation_gate_targets" || ! grep -Fq "Evaluate Policy" <<<"$validation_gate_targets"; then
    echo "Validation Error? node must branch to Error Response and Evaluate Policy in ${workflow_path}" >&2
    exit 1
  fi

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
