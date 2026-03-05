#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

echo "[regression] 1/3 quality gates"
pnpm -r --if-present lint
pnpm -r --if-present typecheck
pnpm -r --if-present test
pnpm -r --if-present build

echo "[regression] 2/3 end-to-end journey"
pnpm e2e

echo "[regression] 3/3 k8s smoke"
if command -v kubectl >/dev/null 2>&1; then
  if kubectl get namespace executor-system >/dev/null 2>&1; then
    bash scripts/ci/k8s_smoke_test.sh
  else
    echo "Skipping k8s smoke: namespace 'executor-system' not found."
  fi
else
  echo "Skipping k8s smoke: kubectl not found."
fi

echo "[regression] complete"
