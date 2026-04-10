#!/usr/bin/env bash
set -euo pipefail

bash scripts/ci/policy_eval_check.sh
bash scripts/ci/memory_ingest_workflow_check.sh
bash scripts/ci/vector_search_workflow_check.sh
bash scripts/ci/audit_append_workflow_check.sh
bash scripts/ci/executor_dispatch_workflow_check.sh
bash scripts/ci/webhook_auth_check.sh
bash scripts/ci/caddy_routing_baseline_check.sh
bash scripts/ci/caddy_security_headers_rate_limit_check.sh
bash scripts/ci/workflow_schema_check.sh
python3 scripts/validate_slack_workflows.py n8n/workflows-v3
python3 -m unittest -v tests.test_slack_ingress_security
python3 -m unittest -v tests.test_slack_request_verifier
