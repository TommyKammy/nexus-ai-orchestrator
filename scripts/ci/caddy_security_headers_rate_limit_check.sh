#!/usr/bin/env bash
set -euo pipefail

CADDYFILE="Caddyfile"
CADDY_DOCKERFILE="docker/caddy/Dockerfile"
CADDY_VALIDATE_IMAGE_TAG="${CADDY_VALIDATE_IMAGE_TAG:-nexus-ai-caddy-validate}"

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

require_pattern 'path[[:space:]]+/webhook/\*' "$CADDYFILE"
require_pattern 'rate_limit' "$CADDYFILE"
require_pattern 'zone[[:space:]]+webhook_limit' "$CADDYFILE"
require_pattern 'match[[:space:]]*\{' "$CADDYFILE"
require_pattern 'key[[:space:]]+\{remote_host\}' "$CADDYFILE"
require_pattern 'events[[:space:]]+30' "$CADDYFILE"
require_pattern 'window[[:space:]]+1m' "$CADDYFILE"
require_pattern 'handle_errors[[:space:]]*\{' "$CADDYFILE"
require_pattern '@rate_limited[[:space:]]+expression[[:space:]]+`\{err\.status_code\}[[:space:]]*==[[:space:]]*429`' "$CADDYFILE"
require_pattern 'respond[[:space:]]+@rate_limited[[:space:]]+429' "$CADDYFILE"
require_pattern 'respond[[:space:]]+@unauthorized[[:space:]]+401' "$CADDYFILE"
if grep -Eq 'not[[:space:]]+path[[:space:]]+/webhook/slack-command[[:space:]]+/webhook/slack-command/\*' "$CADDYFILE"; then
  echo "Slack webhook path must not bypass the shared Caddy rate limit." >&2
  exit 1
fi

rate_limit_respond_line="$(grep -En 'respond[[:space:]]+@rate_limited[[:space:]]+429' "$CADDYFILE" | head -n1 | cut -d: -f1)"
unauthorized_respond_line="$(grep -En 'respond[[:space:]]+@unauthorized[[:space:]]+401' "$CADDYFILE" | head -n1 | cut -d: -f1)"
if [[ -n "$rate_limit_respond_line" && -n "$unauthorized_respond_line" && "$rate_limit_respond_line" -ge "$unauthorized_respond_line" ]]; then
  echo "Webhook rate-limit responder must be declared before unauthorized responder." >&2
  exit 1
fi

# Ensure Caddy image uses pinned versions and includes pinned ratelimit plugin.
require_pattern '^ARG CADDY_VERSION=[0-9]+\.[0-9]+\.[0-9]+$' "$CADDY_DOCKERFILE"
require_pattern '^FROM caddy:\$\{CADDY_VERSION\}-builder AS builder$' "$CADDY_DOCKERFILE"
require_pattern '^FROM caddy:\$\{CADDY_VERSION\}$' "$CADDY_DOCKERFILE"
require_pattern 'github.com/mholt/caddy-ratelimit@v0\.1\.0' "$CADDY_DOCKERFILE"

# Validate the Caddyfile against the built image so matcher/handler regressions fail in CI.
docker build -t "$CADDY_VALIDATE_IMAGE_TAG" -f "$CADDY_DOCKERFILE" docker/caddy >/dev/null
docker run --rm \
  -e N8N_WEBHOOK_API_KEY=test-webhook-key \
  -v "$PWD/$CADDYFILE:/config/Caddyfile:ro" \
  "$CADDY_VALIDATE_IMAGE_TAG" \
  caddy validate --config /config/Caddyfile --adapter caddyfile >/dev/null

echo "Caddy security headers and rate-limit checks passed."
