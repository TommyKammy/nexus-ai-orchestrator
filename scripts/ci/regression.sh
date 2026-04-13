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
K8S_NAMESPACE="${K8S_NAMESPACE:-executor-system}"
if ! command -v kubectl >/dev/null 2>&1; then
  echo "Skipping k8s smoke: kubectl not found."
else
  K8S_CONTEXT="$(kubectl config current-context 2>/dev/null || true)"
  if [[ -z "${K8S_CONTEXT}" ]]; then
    echo "Skipping k8s smoke: kubectl current context is not configured."
  elif ! kubectl cluster-info >/dev/null 2>&1; then
    echo "Skipping k8s smoke: kube cluster for context '${K8S_CONTEXT}' is unavailable."
  elif kubectl get namespace "${K8S_NAMESPACE}" >/dev/null 2>&1; then
    bash scripts/ci/k8s_smoke_test.sh
  else
    ns_check_err="$(kubectl get namespace "${K8S_NAMESPACE}" 2>&1 >/dev/null || true)"
    if echo "${ns_check_err}" | grep -qi "not found"; then
      echo "Skipping k8s smoke: namespace '${K8S_NAMESPACE}' not found."
    else
      echo "k8s smoke gating failed: unable to verify namespace '${K8S_NAMESPACE}'." >&2
      echo "${ns_check_err}" >&2
      exit 1
    fi
  fi
fi

echo "[regression] complete"
