#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

require_pattern() {
  local pattern="$1"
  local file="$2"
  if ! grep -Eq -- "${pattern}" "${file}"; then
    echo "Missing required pattern '${pattern}' in ${file}" >&2
    exit 1
  fi
}

# Existing Caddy security baseline checks (headers + rate limit) must stay green.
bash scripts/ci/caddy_security_headers_rate_limit_check.sh

# Compose executor hardening baseline.
require_pattern 'read_only:[[:space:]]*true' docker-compose.yml
require_pattern 'no-new-privileges:true' docker-compose.yml

# Kubernetes operator hardening baseline.
require_pattern 'runAsNonRoot:[[:space:]]*true' k8s/config/deployment/operator-deployment.yaml
require_pattern 'allowPrivilegeEscalation:[[:space:]]*false' k8s/config/deployment/operator-deployment.yaml
require_pattern 'readOnlyRootFilesystem:[[:space:]]*true' k8s/config/deployment/operator-deployment.yaml
require_pattern 'value:[[:space:]]*"rediss://redis\.executor-system\.svc\.cluster\.local:6379/0"' k8s/config/deployment/operator-deployment.yaml
require_pattern 'secretKeyRef:[[:space:]]*$' k8s/config/deployment/operator-deployment.yaml
require_pattern 'name:[[:space:]]*redis-auth' k8s/config/deployment/operator-deployment.yaml
require_pattern 'secretName:[[:space:]]*redis-tls' k8s/config/deployment/operator-deployment.yaml
require_pattern '--tls-port 6379' k8s/config/deployment/operator-deployment.yaml
require_pattern '--port 0' k8s/config/deployment/operator-deployment.yaml
require_pattern 'tls:' k8s/config/deployment/ingress.yaml
require_pattern 'secretName:[[:space:]]*executor-edge-tls' k8s/config/deployment/ingress.yaml
require_pattern 'nginx\.ingress\.kubernetes\.io/force-ssl-redirect:[[:space:]]*"true"' k8s/config/deployment/ingress.yaml

echo "misconfiguration baseline checks passed."
