#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/docker-compose.yml")
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-240}"

ensure_env_file() {
  if [[ -f "$ENV_FILE" ]]; then
    return
  fi

  cp "$ROOT_DIR/.env.example" "$ENV_FILE"
  cat <<EOF
[bootstrap] Created $ENV_FILE from .env.example.
[bootstrap] Replace CHANGE_ME values before exposing this stack beyond local development.
EOF
}

ensure_runtime_dirs() {
  mkdir -p \
    "$ROOT_DIR/postgres" \
    "$ROOT_DIR/redis" \
    "$ROOT_DIR/logs" \
    "$ROOT_DIR/caddy_data" \
    "$ROOT_DIR/caddy_config" \
    "$ROOT_DIR/policy/runtime"
}

wait_for_service() {
  local service="$1"
  local waited=0
  local interval=5

  while (( waited < TIMEOUT_SECONDS )); do
    local cid status
    cid="$("${COMPOSE[@]}" ps -q "$service" 2>/dev/null || true)"

    if [[ -n "$cid" ]]; then
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
      if [[ "$status" == "healthy" || "$status" == "running" ]]; then
        echo "[bootstrap] $service is $status"
        return 0
      fi
    fi

    sleep "$interval"
    waited=$(( waited + interval ))
  done

  echo "[bootstrap] ERROR: timed out waiting for service '$service'" >&2
  "${COMPOSE[@]}" ps
  return 1
}

run_with_retry() {
  local name="$1"
  shift
  local waited=0
  local interval=5

  while (( waited < TIMEOUT_SECONDS )); do
    if "$@"; then
      echo "[bootstrap] $name check passed"
      return 0
    fi
    sleep "$interval"
    waited=$(( waited + interval ))
  done

  echo "[bootstrap] ERROR: timed out waiting for check '$name'" >&2
  return 1
}

run_health_checks() {
  echo "[bootstrap] Running service health checks..."
  run_with_retry "postgres" docker exec ai-postgres pg_isready -U ai_user -d ai_memory >/dev/null
  run_with_retry "redis" bash -lc "docker exec ai-redis redis-cli ping | grep -q '^PONG$'"
  run_with_retry "policy-bundle-server" curl -fsS http://127.0.0.1:8088/healthz >/dev/null
  run_with_retry "opa" curl -fsS http://127.0.0.1:8181/health >/dev/null
  run_with_retry "caddy-config" docker exec ai-caddy caddy validate --config /etc/caddy/Caddyfile >/dev/null
  echo "[bootstrap] Health checks passed."
}

main() {
  echo "[bootstrap] Root: $ROOT_DIR"
  ensure_env_file
  ensure_runtime_dirs

  echo "[bootstrap] Starting docker compose stack..."
  "${COMPOSE[@]}" up -d --build

  wait_for_service postgres
  wait_for_service redis
  wait_for_service policy-bundle-server
  wait_for_service opa
  wait_for_service n8n
  wait_for_service caddy
  wait_for_service executor

  run_health_checks

  echo
  echo "[bootstrap] Stack is up and healthy."
  "${COMPOSE[@]}" ps
}

main "$@"
