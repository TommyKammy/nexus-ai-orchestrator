#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${POSTGRES_CONTAINER:-ai-postgres}"
DB_USER="${POSTGRES_USER:-ai_user}"
DB_NAME="${POSTGRES_DB:-ai_memory}"
MIN_LISTS="${PGVECTOR_MIN_LISTS:-50}"
MAX_LISTS="${PGVECTOR_MAX_LISTS:-2000}"
LISTS_OVERRIDE="${PGVECTOR_LISTS:-}"

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  echo "POSTGRES_PASSWORD is required in environment." >&2
  exit 1
fi

psql_exec() {
  local sql="$1"
  docker exec -i "$CONTAINER_NAME" env PGPASSWORD="$POSTGRES_PASSWORD" \
    psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -tAc "$sql"
}

table_exists="$(psql_exec "SELECT to_regclass('public.memory_vectors') IS NOT NULL;")"
if [[ "$table_exists" != "t" ]]; then
  echo "memory_vectors table does not exist in ${DB_NAME}. Apply base migration first." >&2
  exit 1
fi

if [[ -n "$LISTS_OVERRIDE" ]]; then
  if ! [[ "$LISTS_OVERRIDE" =~ ^[0-9]+$ ]]; then
    echo "PGVECTOR_LISTS must be an integer." >&2
    exit 1
  fi
  target_lists="$LISTS_OVERRIDE"
else
  row_count="$(psql_exec "SELECT COUNT(*) FROM memory_vectors;")"
  target_lists="$(awk -v n="$row_count" -v min="$MIN_LISTS" -v max="$MAX_LISTS" 'BEGIN { l=int(sqrt(n)); if (l<min) l=min; if (l>max) l=max; print l }')"
fi

if ! [[ "$target_lists" =~ ^[0-9]+$ ]]; then
  echo "Calculated list count is invalid: $target_lists" >&2
  exit 1
fi

echo "Rebuilding idx_memory_vectors_embedding with lists=${target_lists}..."
docker exec -i "$CONTAINER_NAME" env PGPASSWORD="$POSTGRES_PASSWORD" \
  psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 <<SQL
DROP INDEX IF EXISTS idx_memory_vectors_embedding;
CREATE INDEX idx_memory_vectors_embedding
ON memory_vectors
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = ${target_lists});
ANALYZE memory_vectors;
SQL

echo "Updated index definition:"
psql_exec "SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND tablename='memory_vectors' AND indexname='idx_memory_vectors_embedding';"
