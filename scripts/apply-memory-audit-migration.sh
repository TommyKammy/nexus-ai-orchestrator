#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQL_FILES=(
  "$ROOT_DIR/sql/20260304_memory_vectors_audit_events.sql"
  "$ROOT_DIR/sql/20260412_tenant_row_level_security.sql"
)

for sql_file in "${SQL_FILES[@]}"; do
  if [[ ! -f "$sql_file" ]]; then
    echo "SQL file not found: $sql_file" >&2
    exit 1
  fi
done

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  echo "POSTGRES_PASSWORD is required in environment." >&2
  exit 1
fi

for sql_file in "${SQL_FILES[@]}"; do
  docker exec -i ai-postgres \
    env PGPASSWORD="$POSTGRES_PASSWORD" \
    psql -U ai_user -d ai_memory -v ON_ERROR_STOP=1 < "$sql_file"
done

echo "Memory/audit schema migrations applied."
