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

require_positive_int() {
  local value="$1"
  local name="$2"
  if ! [[ "$value" =~ ^[0-9]+$ ]] || [[ "$value" -lt 1 ]]; then
    echo "$name must be a positive integer." >&2
    exit 1
  fi
}

require_positive_int "$MIN_LISTS" "PGVECTOR_MIN_LISTS"
require_positive_int "$MAX_LISTS" "PGVECTOR_MAX_LISTS"
if [[ "$MIN_LISTS" -gt "$MAX_LISTS" ]]; then
  echo "PGVECTOR_MIN_LISTS must be <= PGVECTOR_MAX_LISTS." >&2
  exit 1
fi

table_exists="$(psql_exec "SELECT to_regclass('public.memory_vectors') IS NOT NULL;")"
if [[ "$table_exists" != "t" ]]; then
  echo "memory_vectors table does not exist in ${DB_NAME}. Apply base migration first." >&2
  exit 1
fi

if [[ -n "$LISTS_OVERRIDE" ]]; then
  require_positive_int "$LISTS_OVERRIDE" "PGVECTOR_LISTS"
  target_lists="$LISTS_OVERRIDE"
else
  row_count="$(psql_exec "SELECT COALESCE((SELECT n_live_tup::bigint FROM pg_stat_all_tables WHERE schemaname = 'public' AND relname = 'memory_vectors'), (SELECT reltuples::bigint FROM pg_class WHERE oid = 'public.memory_vectors'::regclass), 0);")"
  target_lists="$(awk -v n="$row_count" -v min="$MIN_LISTS" -v max="$MAX_LISTS" 'BEGIN { if (n < 0) n = 0; l=int(sqrt(n)); if (l<min) l=min; if (l>max) l=max; print l }')"
fi

if ! [[ "$target_lists" =~ ^[0-9]+$ ]] || [[ "$target_lists" -lt 1 ]]; then
  echo "Calculated list count is invalid: $target_lists" >&2
  exit 1
fi

echo "Rebuilding idx_memory_vectors_embedding with lists=${target_lists}..."
docker exec -i "$CONTAINER_NAME" env PGPASSWORD="$POSTGRES_PASSWORD" \
  psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 <<SQL
DROP INDEX IF EXISTS public.idx_memory_vectors_embedding;
CREATE INDEX idx_memory_vectors_embedding
ON public.memory_vectors
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = ${target_lists});
ANALYZE public.memory_vectors;
SQL

echo "Updated index definition:"
psql_exec "SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND tablename='memory_vectors' AND indexname='idx_memory_vectors_embedding';"
