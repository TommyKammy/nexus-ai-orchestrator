#!/usr/bin/env bash
set -euo pipefail

CADDYFILE="Caddyfile"
CADDY_DOCKERFILE="docker/caddy/Dockerfile"

require_pattern() {
  local pattern="$1"
  local file="$2"
  if ! grep -Eq "$pattern" "$file"; then
    echo "Missing expected pattern in ${file}: ${pattern}" >&2
    exit 1
  fi
}

require_pattern 'Strict-Transport-Security[[:space:]]+"max-age=31536000; includeSubDomains; preload"' "$CADDYFILE"
require_pattern 'X-Content-Type-Options[[:space:]]+"nosniff"' "$CADDYFILE"
require_pattern 'X-XSS-Protection[[:space:]]+"1; mode=block"' "$CADDYFILE"
require_pattern 'Referrer-Policy[[:space:]]+"strict-origin-when-cross-origin"' "$CADDYFILE"

require_pattern '@webhook_rate_limited' "$CADDYFILE"
require_pattern 'path[[:space:]]+/webhook/\*' "$CADDYFILE"
require_pattern 'not[[:space:]]+path[[:space:]]+/webhook/slack-command[[:space:]]+/webhook/slack-command/\*' "$CADDYFILE"
require_pattern 'rate_limit' "$CADDYFILE"
require_pattern 'zone[[:space:]]+webhook_limit' "$CADDYFILE"
require_pattern 'key[[:space:]]+\{remote_host\}' "$CADDYFILE"
require_pattern 'events[[:space:]]+30' "$CADDYFILE"
require_pattern 'window[[:space:]]+1m' "$CADDYFILE"
require_pattern 'respond[[:space:]]+@webhook_rate_limited[[:space:]]+429' "$CADDYFILE"

# Ensure Caddy image uses pinned versions and includes pinned ratelimit plugin.
require_pattern '^ARG CADDY_VERSION=[0-9]+\.[0-9]+\.[0-9]+$' "$CADDY_DOCKERFILE"
require_pattern '^FROM caddy:\$\{CADDY_VERSION\}-builder AS builder$' "$CADDY_DOCKERFILE"
require_pattern '^FROM caddy:\$\{CADDY_VERSION\}$' "$CADDY_DOCKERFILE"
require_pattern 'github.com/mholt/caddy-ratelimit@v0\.1\.0' "$CADDY_DOCKERFILE"

echo "Caddy security headers and rate-limit checks passed."
