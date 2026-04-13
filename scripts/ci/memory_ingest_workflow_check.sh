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

service_boundary_workflows=(
  "n8n/workflows-v3/01_memory_ingest.json"
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

query_highest_positional_placeholder() {
  local query="$1"
  python3 - "$query" <<'PY'
import re
import sys

query = sys.argv[1]
placeholders = [int(match) for match in re.findall(r'\$(\d+)', query)]
print(max(placeholders, default=0))
PY
}

query_replacement_binding_count() {
  local query_replacement="$1"
  python3 - "$query_replacement" <<'PY'
import sys

expr = sys.argv[1].strip()
if expr.startswith('={{') and expr.endswith('}}'):
    expr = expr[3:-2].strip()

if not expr.startswith('[') or not expr.endswith(']'):
    print("unparseable")
    raise SystemExit(0)

body = expr[1:-1]
depth = 0
count = 0
token_started = False
in_single = False
in_double = False
in_backtick = False
escape = False

for ch in body:
    if in_single:
        token_started = True
        if escape:
            escape = False
        elif ch == '\\':
            escape = True
        elif ch == "'":
            in_single = False
        continue

    if in_double:
        token_started = True
        if escape:
            escape = False
        elif ch == '\\':
            escape = True
        elif ch == '"':
            in_double = False
        continue

    if in_backtick:
        token_started = True
        if escape:
            escape = False
        elif ch == '\\':
            escape = True
        elif ch == '`':
            in_backtick = False
        continue

    if ch == "'":
        in_single = True
        token_started = True
        continue

    if ch == '"':
        in_double = True
        token_started = True
        continue

    if ch == '`':
        in_backtick = True
        token_started = True
        continue

    if ch in '([{':
        depth += 1
        token_started = True
        continue

    if ch in ')]}':
        if depth == 0:
            print("unparseable")
            raise SystemExit(0)
        depth -= 1
        token_started = True
        continue

    if ch == ',' and depth == 0:
        if token_started:
            count += 1
            token_started = False
        continue

    if not ch.isspace():
        token_started = True

if in_single or in_double or in_backtick or depth != 0:
    print("unparseable")
    raise SystemExit(0)

if token_started:
    count += 1

print(count)
PY
}

check_insert_vector_contract() {
  local workflow_path="$1"
  local query
  local query_replacement

  query="$(jq -r '.nodes[] | select(.type == "n8n-nodes-base.postgres" and .name == "Insert Vector") | .parameters.query' "$workflow_path")"
  query_replacement="$(jq -r '.nodes[] | select(.type == "n8n-nodes-base.postgres" and .name == "Insert Vector") | .parameters.additionalFields.queryReplacement' "$workflow_path")"

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

  if ! grep -Fq '.json.content_hash' <<<"$query_replacement"; then
    die "Insert Vector queryReplacement in ${workflow_path} must preserve content_hash"
  fi
}

check_postgres_node() {
  local workflow_path="$1"
  local node_name="$2"
  local query
  local query_replacement
  local has_query_replacement="false"
  local highest_placeholder
  local binding_count

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
    highest_placeholder="$(query_highest_positional_placeholder "$query")"
    binding_count="$(query_replacement_binding_count "$query_replacement")"
    if [[ ! "$binding_count" =~ ^[0-9]+$ ]]; then
      die "queryReplacement must be a statically countable array expression in ${workflow_path} :: ${node_name}"
    fi
    if (( binding_count < highest_placeholder )); then
      die "queryReplacement only provides ${binding_count} bindings for ${highest_placeholder} positional placeholders in ${workflow_path} :: ${node_name}"
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

check_http_node_contract() {
  local workflow_path="$1"
  local node_name="$2"
  local expected_url="$3"
  local json_body="$4"
  local header_json="$5"
  shift 5
  local required_patterns=("$@")
  local actual_type
  local method
  local url
  local header_dump

  actual_type="$(jq -r --arg node_name "$node_name" '.nodes[] | select(.name == $node_name) | .type' "$workflow_path")"
  method="$(jq -r --arg node_name "$node_name" '.nodes[] | select(.name == $node_name) | .parameters.method' "$workflow_path")"
  url="$(jq -r --arg node_name "$node_name" '.nodes[] | select(.name == $node_name) | .parameters.url' "$workflow_path")"
  header_dump="$(jq -c --arg node_name "$node_name" '.nodes[] | select(.name == $node_name) | .parameters.headerParameters.parameters // []' "$workflow_path")"

  if [[ "$actual_type" != "n8n-nodes-base.httpRequest" ]]; then
    die "${node_name} must use httpRequest in ${workflow_path}"
  fi
  if [[ "$method" != "POST" ]]; then
    die "${node_name} must use POST in ${workflow_path}"
  fi
  if [[ "$url" != "$expected_url" ]]; then
    die "${node_name} must call ${expected_url} in ${workflow_path}"
  fi

  for pattern in "${required_patterns[@]}"; do
    if ! grep -Fq "$pattern" <<<"$json_body"; then
      die "${node_name} body is missing '${pattern}' in ${workflow_path}"
    fi
  done

  if [[ -n "$header_json" && "$header_json" != "null" ]]; then
    if ! grep -Fq "X-Authenticated-Tenant-Id" <<<"$header_dump"; then
      die "${node_name} must forward X-Authenticated-Tenant-Id in ${workflow_path}"
    fi
  fi

  if ! grep -Fq "X-API-Key" <<<"$header_dump"; then
    die "${node_name} must forward X-API-Key in ${workflow_path}"
  fi
  if ! grep -Fq "POLICY_BUNDLE_INTERNAL_API_KEY" <<<"$header_dump" && ! grep -Fq "N8N_WEBHOOK_API_KEY" <<<"$header_dump"; then
    die "${node_name} must source X-API-Key from workflow environment in ${workflow_path}"
  fi
}

check_service_boundary_workflow() {
  local workflow_path="$1"
  local postgres_count
  local insert_facts_body
  local insert_vector_body
  local insert_audit_body
  local insert_vector_headers
  local insert_audit_headers

  postgres_count="$(jq -r '[.nodes[] | select(.type == "n8n-nodes-base.postgres")] | length' "$workflow_path")"
  if [[ "$postgres_count" != "0" ]]; then
    die "Service-boundary workflow must not keep Postgres nodes in ${workflow_path}"
  fi

  insert_facts_body="$(jq -r '.nodes[] | select(.name == "Insert Facts") | .parameters.jsonBody' "$workflow_path")"
  insert_vector_body="$(jq -r '.nodes[] | select(.name == "Insert Vector") | .parameters.jsonBody' "$workflow_path")"
  insert_audit_body="$(jq -r '.nodes[] | select(.name == "Insert Audit") | .parameters.jsonBody' "$workflow_path")"
  insert_vector_headers="$(jq -c '.nodes[] | select(.name == "Insert Vector") | .parameters.headerParameters.parameters // []' "$workflow_path")"
  insert_audit_headers="$(jq -c '.nodes[] | select(.name == "Insert Audit") | .parameters.headerParameters.parameters // []' "$workflow_path")"

  check_http_node_contract \
    "$workflow_path" \
    "Insert Facts" \
    "http://policy-bundle-server:8088/internal/tenant-data/memory/facts" \
    "$insert_facts_body" \
    "null" \
    "facts"

  check_http_node_contract \
    "$workflow_path" \
    "Insert Vector" \
    "http://policy-bundle-server:8088/internal/tenant-data/memory/vector" \
    "$insert_vector_body" \
    "$insert_vector_headers" \
    "tenant_id" \
    "content_hash" \
    "metadata_jsonb"

  check_http_node_contract \
    "$workflow_path" \
    "Insert Audit" \
    "http://policy-bundle-server:8088/internal/tenant-data/audit/event" \
    "$insert_audit_body" \
    "$insert_audit_headers" \
    "tenant_id" \
    "policy"
}

for workflow_path in "${covered_workflows[@]}"; do
  if printf '%s\n' "${service_boundary_workflows[@]}" | grep -Fxq "$workflow_path"; then
    check_service_boundary_workflow "$workflow_path"
    continue
  fi
  check_workflow "$workflow_path"
done

check_insert_vector_contract "n8n/workflows/01_memory_ingest.json"
check_insert_vector_contract "n8n/workflows/01_memory_ingest_v3_cached.json"

echo "Memory ingest workflow metadata checks passed."
