#!/usr/bin/env bash
set -euo pipefail

bash scripts/ci/n8n_import_test.sh
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-n8n}" bash scripts/ci/compose_core_journey.sh
