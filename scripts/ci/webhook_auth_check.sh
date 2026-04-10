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

check_workflow_auth() {
  local workflow_path="$1"
  local webhook_paths

  webhook_paths="$(
    jq -r '.nodes[]? | select(.type == "n8n-nodes-base.webhook") | .parameters.path // empty' "$workflow_path"
  )"

  [[ -n "$webhook_paths" ]] || return 0

  while IFS= read -r webhook_path; do
    [[ -n "$webhook_path" ]] || continue

    if [[ "$webhook_path" == "slack-command" ]]; then
      continue
    fi

    if ! jq -e --arg webhook_path "$webhook_path" '
      (.nodes // []) as $nodes
      | (.connections // {}) as $connections
      | [ $nodes[]? | select(.type == "n8n-nodes-base.webhook" and (.parameters.path // "") == $webhook_path) ] as $webhook_nodes
      | ($webhook_nodes | length) == 1
        and any($nodes[]?;
          .name == "Check Webhook Auth"
          and .type == "n8n-nodes-base.code"
          and ((.parameters.jsCode // "") | test("N8N_WEBHOOK_API_KEY"))
          and ((.parameters.jsCode // "") | test("webhook_auth"))
        )
        and any($nodes[]?;
          .name == "Webhook Authorized?"
          and .type == "n8n-nodes-base.if"
          and ((.parameters.conditions | tostring) | contains("webhook_auth.authenticated === true"))
        )
        and any($nodes[]?;
          .name == "Unauthorized Response"
          and .type == "n8n-nodes-base.respondToWebhook"
          and (((.parameters.options.responseCode // .parameters.responseCode // "") | tostring) == "401")
          and (
            ((.parameters.options.body // .parameters.body // .parameters.options.responseBody // .parameters.responseBody // "") | tostring) as $response_body
            | (($response_body | contains("status: '\''error'\''")) or ($response_body | contains("\"status\":\"error\"")))
            and ($response_body | contains("message"))
          )
        )
        and (($connections[$webhook_nodes[0].name].main[0][0].node // "") == "Check Webhook Auth")
        and (($connections["Check Webhook Auth"].main[0][0].node // "") == "Webhook Authorized?")
        and (($connections["Webhook Authorized?"].main[1][0].node // "") == "Unauthorized Response")
    ' "$workflow_path" >/dev/null; then
      echo "Workflow ${workflow_path} exposes /webhook/${webhook_path} without the required auth gate wiring." >&2
      exit 1
    fi
  done <<<"$webhook_paths"
}

require_pattern "path /webhook/*" "$CADDYFILE"
require_pattern "header({'X-API-Key': {env.N8N_WEBHOOK_API_KEY}})" "$CADDYFILE"
require_pattern "header({'Authorization': 'Bearer ' + {env.N8N_WEBHOOK_API_KEY}})" "$CADDYFILE"
require_pattern "respond @unauthorized 401" "$CADDYFILE"
require_pattern "Unauthorized: Invalid or missing API key" "$CADDYFILE"

# Reject hex-like hardcoded key literals in X-API-Key checks and injection.
reject_pattern 'X-API-Key[[:space:]]+[0-9a-fA-F]{32,}' "$CADDYFILE"
# Reject internal key-injection route for externally reachable webhook path.
reject_pattern 'handle[[:space:]]+/webhook/chat/router-v1' "$CADDYFILE"

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

if ! grep -Fq 'N8N_WEBHOOK_API_KEY: ${N8N_WEBHOOK_API_KEY:?set N8N_WEBHOOK_API_KEY}' <<<"$caddy_block"; then
  echo "Caddy service must include N8N_WEBHOOK_API_KEY env wiring in ${COMPOSE_FILE}" >&2
  exit 1
fi

while IFS= read -r workflow_path; do
  check_workflow_auth "$workflow_path"
done < <(find n8n/workflows n8n/workflows-v3 -type f -name '*.json' | sort)

echo "Webhook auth configuration checks passed."
