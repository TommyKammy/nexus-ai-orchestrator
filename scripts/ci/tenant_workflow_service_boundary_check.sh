#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

python3 "${REPO_ROOT}/scripts/check_tenant_workflow_service_boundary.py" \
  --repo-root "${REPO_ROOT}"
