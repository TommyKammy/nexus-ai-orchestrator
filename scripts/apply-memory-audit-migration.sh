#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQL_FILE="$ROOT_DIR/sql/20260304_memory_vectors_audit_events.sql"

if [[ ! -f "$SQL_FILE" ]]; then
  echo "SQL file not found: $SQL_FILE" >&2
  exit 1
fi

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  echo "POSTGRES_PASSWORD is required in environment." >&2
  exit 1
fi

docker exec -i ai-postgres \
  env PGPASSWORD="$POSTGRES_PASSWORD" \
  psql -U ai_user -d ai_memory -v ON_ERROR_STOP=1 < "$SQL_FILE"

echo "Memory/audit base schema migration applied."
