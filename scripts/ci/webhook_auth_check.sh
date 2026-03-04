#!/usr/bin/env bash
set -euo pipefail

CADDYFILE="Caddyfile"
COMPOSE_FILE="docker-compose.yml"

require_pattern() {
  local pattern="$1"
  local file="$2"
  if ! grep -Fq "$pattern" "$file"; then
    echo "Missing required pattern in ${file}: ${pattern}" >&2
    exit 1
  fi
}

reject_pattern() {
  local pattern="$1"
  local file="$2"
  if grep -Eq "$pattern" "$file"; then
    echo "Forbidden hardcoded webhook API key pattern found in ${file}: ${pattern}" >&2
    exit 1
  fi
}

require_pattern "handle /webhook/chat/router-v1" "$CADDYFILE"
require_pattern "header_up X-API-Key {env.N8N_WEBHOOK_API_KEY}" "$CADDYFILE"
require_pattern "path /webhook/*" "$CADDYFILE"
require_pattern "not header X-API-Key {env.N8N_WEBHOOK_API_KEY}" "$CADDYFILE"
require_pattern "respond @unauthorized 401" "$CADDYFILE"
require_pattern "Unauthorized: Invalid or missing API key" "$CADDYFILE"

# Reject hex-like hardcoded key literals in X-API-Key checks and injection.
reject_pattern 'X-API-Key\s+[0-9a-fA-F]{32,}' "$CADDYFILE"

# Caddy service must receive webhook auth key from environment.
caddy_block="$(
  awk '
    /^[[:space:]]{2}caddy:$/ { in_caddy=1; print; next }
    in_caddy && /^[[:space:]]{2}[a-zA-Z0-9_.-]+:$/ { in_caddy=0 }
    in_caddy { print }
  ' "$COMPOSE_FILE"
)"

if [[ -z "$caddy_block" ]]; then
  echo "Failed to parse caddy service block from ${COMPOSE_FILE}" >&2
  exit 1
fi

if ! grep -Fq 'N8N_WEBHOOK_API_KEY: ${N8N_WEBHOOK_API_KEY}' <<<"$caddy_block"; then
  echo "Caddy service must include N8N_WEBHOOK_API_KEY env wiring in ${COMPOSE_FILE}" >&2
  exit 1
fi

echo "Webhook auth configuration checks passed."
