#!/usr/bin/env bash
set -euo pipefail

bash scripts/ci/n8n_import_test.sh
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-n8n}" \
N8N_WEBHOOK_API_KEY="${N8N_WEBHOOK_API_KEY:-ci-local-webhook-key}" \
  bash scripts/ci/compose_core_journey.sh
