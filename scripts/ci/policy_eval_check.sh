#!/usr/bin/env bash
set -euo pipefail

OPA_IMAGE="openpolicyagent/opa:0.68.0"
POLICY_DIR="$PWD/policy/opa"

run_eval() {
  local input_json="$1"
  printf '%s\n' "$input_json" | docker run --rm -i \
    -v "$POLICY_DIR:/policy" \
    "$OPA_IMAGE" eval --stdin-input -f json \
    -d /policy/authz.rego \
    -d /policy/risk.rego \
    -d /policy/data.json \
    "data.ai.policy.result" | jq -ce '.result[0].expressions[0].value'
}

docker run --rm -v "$POLICY_DIR:/policy" "$OPA_IMAGE" \
  check /policy/authz.rego /policy/risk.rego

ALLOW_INPUT='{"subject":{"tenant_id":"t1","scope":"analysis","role":"api"},"resource":{"tenant_id":"t1","scope":"analysis","template":"default","language":"python","task_type":"code_execution"},"action":"executor.execute","context":{"request_id":"ci-allow","payload_size":100,"network_enabled":false}}'
ALLOW_RESULT="$(run_eval "$ALLOW_INPUT")"
echo "$ALLOW_RESULT" | jq -e '
  .decision == "allow" and
  .allow == true and
  .requires_approval == false and
  .risk_score == 0 and
  (.reasons | type == "array" and length == 0)
' >/dev/null

APPROVAL_INPUT='{"subject":{"tenant_id":"t1","scope":"analysis","role":"api","network_admin":true},"resource":{"tenant_id":"t1","scope":"analysis","template":"default","language":"python","task_type":"code_execution"},"action":"executor.execute","context":{"request_id":"ci-approval","payload_size":100,"network_enabled":true}}'
APPROVAL_RESULT="$(run_eval "$APPROVAL_INPUT")"
echo "$APPROVAL_RESULT" | jq -e '
  .decision == "requires_approval" and
  .allow == false and
  .requires_approval == true and
  .risk_score >= 40 and
  (.reasons | index("high_risk_requires_approval") != null)
' >/dev/null

DENY_INPUT='{"subject":{"tenant_id":"t1","scope":"analysis","role":"api"},"resource":{"tenant_id":"t1","scope":"analysis","template":"default","language":"python","task_type":"unknown_task"},"action":"executor.execute","context":{"request_id":"ci-deny","payload_size":100,"network_enabled":false}}'
DENY_RESULT="$(run_eval "$DENY_INPUT")"
echo "$DENY_RESULT" | jq -e '
  .decision == "deny" and
  .allow == false and
  .requires_approval == false and
  .risk_score >= 35 and
  (.reasons | index("task_type_not_allowed") != null)
' >/dev/null

echo "OPA policy check/eval passed for allow/requires_approval/deny contracts."
