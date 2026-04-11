#!/usr/bin/env bash
set -euo pipefail

# Guardrail intent:
# - inspect every Postgres node in the memory-ingest workflow family
# - fail fast on raw template interpolation inside SQL text
# - require positional placeholders plus queryReplacement when runtime values are bound
# - allow constant SQL that does not accept runtime input

covered_workflows=(
  "n8n/workflows/01_memory_ingest.json"
  "n8n/workflows-v3/01_memory_ingest.json"
  "n8n/workflows/01_memory_ingest_v3_cached.json"
)

insert_vector_required_patterns=(
  "content_hash"
  "metadata_jsonb"
  "tags"
  "source"
  "ON CONFLICT (tenant_id, scope, content_hash)"
  "WHERE content_hash IS NOT NULL"
  "RETURNING id, content_hash"
  '$1'
  '$2'
  '$3'
)

die() {
  echo "$1" >&2
  exit 1
}

query_contains_raw_interpolation() {
  local query="$1"
  grep -Eq '\{\{|\$\{' <<<"$query"
}

query_has_positional_placeholders() {
  local query="$1"
  grep -Eq '\$[0-9]+' <<<"$query"
}

check_insert_vector_contract() {
  local workflow_path="$1"
  local query
  local query_replacement

  query="$(jq -r '.nodes[] | select(.name == "Insert Vector") | .parameters.query' "$workflow_path")"
  query_replacement="$(jq -r '.nodes[] | select(.name == "Insert Vector") | .parameters.additionalFields.queryReplacement' "$workflow_path")"

  if [[ -z "$query" || "$query" == "null" ]]; then
    die "Insert Vector query not found: ${workflow_path}"
  fi
  if [[ -z "$query_replacement" || "$query_replacement" == "null" ]]; then
    die "Insert Vector queryReplacement not found: ${workflow_path}"
  fi

  for pattern in "${insert_vector_required_patterns[@]}"; do
    if ! grep -Fq "$pattern" <<<"$query"; then
      die "Insert Vector in ${workflow_path} is missing '${pattern}'"
    fi
  done

  if ! grep -Fq "content_hash" <<<"$query_replacement"; then
    die "Insert Vector queryReplacement in ${workflow_path} must preserve content_hash"
  fi
}

check_postgres_node() {
  local workflow_path="$1"
  local node_name="$2"
  local query
  local query_replacement
  local has_query_replacement="false"

  query="$(jq -r --arg node_name "$node_name" '.nodes[] | select(.type == "n8n-nodes-base.postgres" and .name == $node_name) | .parameters.query' "$workflow_path")"
  query_replacement="$(jq -r --arg node_name "$node_name" '.nodes[] | select(.type == "n8n-nodes-base.postgres" and .name == $node_name) | .parameters.additionalFields.queryReplacement' "$workflow_path")"

  if [[ -z "$query" || "$query" == "null" ]]; then
    die "Postgres node '${node_name}' is missing a query in ${workflow_path}"
  fi

  if [[ -n "$query_replacement" && "$query_replacement" != "null" ]]; then
    has_query_replacement="true"
  fi

  if query_contains_raw_interpolation "$query"; then
    die "Raw SQL interpolation detected in ${workflow_path} :: ${node_name}"
  fi

  if query_has_positional_placeholders "$query"; then
    if [[ "$has_query_replacement" != "true" ]]; then
      die "Parameterized SQL requires queryReplacement in ${workflow_path} :: ${node_name}"
    fi
    return
  fi

  if [[ "$has_query_replacement" == "true" ]]; then
    die "queryReplacement without positional placeholders in ${workflow_path} :: ${node_name}"
  fi
}

check_workflow() {
  local workflow_path="$1"
  local node_names_raw
  local node_name

  if [[ ! -f "$workflow_path" ]]; then
    die "Workflow not found: ${workflow_path}"
  fi

  node_names_raw="$(jq -r '.nodes[] | select(.type == "n8n-nodes-base.postgres") | .name' "$workflow_path")"

  if [[ -z "$node_names_raw" ]]; then
    die "No Postgres nodes found in ${workflow_path}"
  fi

  while IFS= read -r node_name; do
    check_postgres_node "$workflow_path" "$node_name"
  done <<<"$node_names_raw"
}

for workflow_path in "${covered_workflows[@]}"; do
  check_workflow "$workflow_path"
done

check_insert_vector_contract "n8n/workflows/01_memory_ingest.json"
check_insert_vector_contract "n8n/workflows-v3/01_memory_ingest.json"

echo "Memory ingest workflow metadata checks passed."
