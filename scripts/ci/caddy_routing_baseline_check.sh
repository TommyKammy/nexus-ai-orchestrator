#!/usr/bin/env bash
set -euo pipefail

CADDYFILE="Caddyfile"

require_pattern() {
  local pattern="$1"
  local file="$2"
  if ! grep -Eq "$pattern" "$file"; then
    echo "Missing expected pattern in ${file}: ${pattern}" >&2
    exit 1
  fi
}

reject_pattern() {
  local pattern="$1"
  local file="$2"
  if grep -Eq "$pattern" "$file"; then
    echo "Unexpected insecure pattern in ${file}: ${pattern}" >&2
    exit 1
  fi
}

require_pattern '@internal_only[[:space:]]+path[[:space:]]+/internal/\*[[:space:]]+/executor/\*[[:space:]]+/opa/\*[[:space:]]+/postgres/\*[[:space:]]+/redis/\*' "$CADDYFILE"
require_pattern 'respond[[:space:]]+@internal_only[[:space:]]+404' "$CADDYFILE"
require_pattern 'handle[[:space:]]+/policy-ui\*' "$CADDYFILE"
require_pattern 'reverse_proxy[[:space:]]+policy-bundle-server:8088' "$CADDYFILE"
require_pattern 'reverse_proxy[[:space:]]+n8n:5678' "$CADDYFILE"

# Caddy should not expose internal service backends directly.
reject_pattern 'reverse_proxy[[:space:]]+(executor|ai-executor|opa|postgres|redis):' "$CADDYFILE"

# Internal route deny must appear before the default n8n reverse proxy.
deny_line="$(grep -nE 'respond[[:space:]]+@internal_only[[:space:]]+404' "$CADDYFILE" | head -n1 | cut -d: -f1)"
proxy_line="$(grep -nE '^[[:space:]]*reverse_proxy[[:space:]]+n8n:5678' "$CADDYFILE" | head -n1 | cut -d: -f1)"

if [[ -z "$deny_line" || -z "$proxy_line" ]]; then
  echo "Unable to evaluate route order in ${CADDYFILE}." >&2
  exit 1
fi

if (( deny_line >= proxy_line )); then
  echo "Internal deny route must be defined before default n8n proxy in ${CADDYFILE}." >&2
  exit 1
fi

echo "Caddy routing baseline checks passed."
