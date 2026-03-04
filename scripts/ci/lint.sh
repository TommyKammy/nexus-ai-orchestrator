#!/usr/bin/env bash
set -euo pipefail

docker run --rm -v "$PWD/policy/opa:/policy" openpolicyagent/opa:0.68.0 \
  check /policy/authz.rego /policy/risk.rego
python3 scripts/validate_slack_workflows.py n8n/workflows-v3
