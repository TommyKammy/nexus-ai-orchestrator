#!/usr/bin/env bash
set -euo pipefail

bash scripts/ci/policy_eval_check.sh
python3 scripts/validate_slack_workflows.py n8n/workflows-v3
