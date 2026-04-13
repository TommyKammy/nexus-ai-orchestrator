#!/usr/bin/env bash
set -euo pipefail

POLICY_BUNDLE_INTERNAL_API_KEY="${POLICY_BUNDLE_INTERNAL_API_KEY:-${N8N_WEBHOOK_API_KEY:-ci-local-webhook-key}}"

bash scripts/ci/n8n_import_test.sh
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-n8n}" \
N8N_WEBHOOK_API_KEY="${N8N_WEBHOOK_API_KEY:-ci-local-webhook-key}" \
POLICY_BUNDLE_INTERNAL_API_KEY="${POLICY_BUNDLE_INTERNAL_API_KEY}" \
  bash scripts/ci/compose_core_journey.sh
