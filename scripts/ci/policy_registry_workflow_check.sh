#!/usr/bin/env bash
set -euo pipefail

# Parse the stored n8n expression statically so the gate can validate binding counts without executing workflow code.
count_n8n_query_replacement_bindings() {
  local query_replacement="$1"
  local node_name="$2"
  local workflow_path="$3"

  awk -v node_name="$node_name" -v workflow_path="$workflow_path" '
    function fail(reason) {
      printf "%s for '\''%s'\'' in %s\n", reason, node_name, workflow_path > "/dev/stderr"
      exit 1
    }

    {
      expr = expr $0 "\n"
    }

    END {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", expr)
      if (expr ~ /^=\{\{/) {
        sub(/^=\{\{[[:space:]]*/, "", expr)
        sub(/[[:space:]]*\}\}$/, "", expr)
      }
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", expr)

      if (substr(expr, 1, 1) != "[") {
        fail("queryReplacement must be an array expression")
      }

      count = 0
      array_depth = 0
      brace_depth = 0
      paren_depth = 0
      in_token = 0
      in_single = 0
      in_double = 0
      in_template = 0
      in_line_comment = 0
      in_block_comment = 0
      escape = 0

      for (i = 1; i <= length(expr); i++) {
        ch = substr(expr, i, 1)

        if (in_line_comment) {
          if (ch == "\n") {
            in_line_comment = 0
          }
          continue
        }

        if (in_block_comment) {
          if (ch == "*" && i < length(expr) && substr(expr, i + 1, 1) == "/") {
            in_block_comment = 0
            i++
          }
          continue
        }

        if (escape) {
          escape = 0
          continue
        }

        if (in_single) {
          if (ch == "\\") {
            escape = 1
          } else if (ch == "'\''") {
            in_single = 0
          }
          continue
        }

        if (in_double) {
          if (ch == "\\") {
            escape = 1
          } else if (ch == "\"") {
            in_double = 0
          }
          continue
        }

        if (in_template) {
          if (ch == "\\") {
            escape = 1
          } else if (ch == "`") {
            in_template = 0
          }
          continue
        }

        if (ch == "'\''") {
          in_single = 1
          if (array_depth >= 1) {
            in_token = 1
          }
          continue
        }

        if (ch == "\"") {
          in_double = 1
          if (array_depth >= 1) {
            in_token = 1
          }
          continue
        }

        if (ch == "`") {
          in_template = 1
          if (array_depth >= 1) {
            in_token = 1
          }
          continue
        }

        if (ch == "/" && i < length(expr)) {
          next_ch = substr(expr, i + 1, 1)
          if (next_ch == "/") {
            in_line_comment = 1
            i++
            continue
          }
          if (next_ch == "*") {
            in_block_comment = 1
            i++
            continue
          }
        }

        if (ch ~ /[[:space:]]/) {
          continue
        }

        if (array_depth == 0) {
          if (ch != "[") {
            fail("queryReplacement must contain a single array expression")
          }
          array_depth = 1
          continue
        }

        if (ch == "," && array_depth == 1 && brace_depth == 0 && paren_depth == 0) {
          if (!in_token) {
            fail("queryReplacement contains an empty binding slot")
          }
          count++
          in_token = 0
          continue
        }

        if (ch == "]" && array_depth == 1 && brace_depth == 0 && paren_depth == 0) {
          if (in_token) {
            count++
            in_token = 0
          }
          array_depth = 0
          continue
        }

        if (ch == "[") {
          array_depth++
          in_token = 1
          continue
        }

        if (ch == "]") {
          if (array_depth <= 1) {
            fail("queryReplacement has an unexpected closing bracket")
          }
          array_depth--
          continue
        }

        if (ch == "{") {
          brace_depth++
          in_token = 1
          continue
        }

        if (ch == "}") {
          if (brace_depth == 0) {
            fail("queryReplacement has an unexpected closing brace")
          }
          brace_depth--
          continue
        }

        if (ch == "(") {
          paren_depth++
          in_token = 1
          continue
        }

        if (ch == ")") {
          if (paren_depth == 0) {
            fail("queryReplacement has an unexpected closing parenthesis")
          }
          paren_depth--
          continue
        }

        in_token = 1
      }

      if (escape || in_single || in_double || in_template) {
        fail("queryReplacement has an unterminated string literal")
      }
      if (in_block_comment) {
        fail("queryReplacement has an unterminated block comment")
      }
      if (array_depth != 0 || brace_depth != 0 || paren_depth != 0) {
        fail("queryReplacement has unbalanced delimiters")
      }

      print count
    }
  ' <<<"$query_replacement"
}

strip_sql_noncode() {
  awk '
    function emit_replacement(ch) {
      if (ch == "\n") {
        printf "\n"
      } else {
        printf " "
      }
    }

    function consume_dollar_tag(text, start,    ch, i, tag) {
      if (substr(text, start, 1) != "$") {
        return ""
      }

      ch = substr(text, start + 1, 1)
      if (ch == "$") {
        return "$$"
      }

      if (ch !~ /[A-Za-z_]/) {
        return ""
      }

      tag = "$" ch
      for (i = start + 2; i <= length(text); i++) {
        ch = substr(text, i, 1)
        if (ch == "$") {
          return tag "$"
        }
        if (ch !~ /[A-Za-z0-9_]/) {
          return ""
        }
        tag = tag ch
      }

      return ""
    }

    {
      sql = sql $0 "\n"
    }

    END {
      state = "code"
      block_depth = 0
      dollar_tag = ""

      for (i = 1; i <= length(sql); i++) {
        ch = substr(sql, i, 1)
        next_ch = (i < length(sql)) ? substr(sql, i + 1, 1) : ""

        if (state == "line_comment") {
          emit_replacement(ch)
          if (ch == "\n") {
            state = "code"
          }
          continue
        }

        if (state == "block_comment") {
          if (ch == "/" && next_ch == "*") {
            emit_replacement(ch)
            emit_replacement(next_ch)
            block_depth++
            i++
            continue
          }

          if (ch == "*" && next_ch == "/") {
            emit_replacement(ch)
            emit_replacement(next_ch)
            block_depth--
            i++
            if (block_depth == 0) {
              state = "code"
            }
            continue
          }

          emit_replacement(ch)
          continue
        }

        if (state == "single_quote") {
          if (ch == "'\''" && next_ch == "'\''") {
            emit_replacement(ch)
            emit_replacement(next_ch)
            i++
            continue
          }

          emit_replacement(ch)
          if (ch == "'\''") {
            state = "code"
          }
          continue
        }

        if (state == "double_quote") {
          if (ch == "\"" && next_ch == "\"") {
            emit_replacement(ch)
            emit_replacement(next_ch)
            i++
            continue
          }

          emit_replacement(ch)
          if (ch == "\"") {
            state = "code"
          }
          continue
        }

        if (state == "dollar_quote") {
          if (substr(sql, i, length(dollar_tag)) == dollar_tag) {
            for (j = 1; j <= length(dollar_tag); j++) {
              emit_replacement(substr(dollar_tag, j, 1))
            }
            i += length(dollar_tag) - 1
            state = "code"
            continue
          }

          emit_replacement(ch)
          continue
        }

        if (ch == "-" && next_ch == "-") {
          emit_replacement(ch)
          emit_replacement(next_ch)
          state = "line_comment"
          i++
          continue
        }

        if (ch == "/" && next_ch == "*") {
          emit_replacement(ch)
          emit_replacement(next_ch)
          state = "block_comment"
          block_depth = 1
          i++
          continue
        }

        if (ch == "'\''") {
          emit_replacement(ch)
          state = "single_quote"
          continue
        }

        if (ch == "\"") {
          emit_replacement(ch)
          state = "double_quote"
          continue
        }

        dollar_tag = consume_dollar_tag(sql, i)
        if (dollar_tag != "") {
          for (j = 1; j <= length(dollar_tag); j++) {
            emit_replacement(substr(dollar_tag, j, 1))
          }
          i += length(dollar_tag) - 1
          state = "dollar_quote"
          continue
        }

        printf "%s", ch
      }

      if (state == "block_comment") {
        print "SQL contains an unterminated block comment" > "/dev/stderr"
        exit 1
      }

      if (state == "single_quote" || state == "double_quote" || state == "dollar_quote") {
        print "SQL contains an unterminated quoted literal" > "/dev/stderr"
        exit 1
      }
    }
  '
}

require_parameterized_query() {
  local workflow_path="$1"
  local node_name="$2"
  shift 2

  local matched_nodes
  local match_count
  local query
  local query_replacement
  local replacement_count
  local max_placeholder
  local normalized_query
  matched_nodes="$(jq -c --arg node_name "$node_name" '[.nodes[] | select(.name == $node_name)]' "$workflow_path")"
  match_count="$(jq -r 'length' <<<"$matched_nodes")"

  if [[ "$match_count" -ne 1 ]]; then
    echo "Expected exactly 1 node named '${node_name}' in ${workflow_path}, found ${match_count}" >&2
    exit 1
  fi

  query="$(jq -r '.[0].parameters.query' <<<"$matched_nodes")"
  query_replacement="$(jq -r '.[0].parameters.additionalFields.queryReplacement' <<<"$matched_nodes")"

  if [[ -z "$query" || "$query" == "null" ]]; then
    echo "Query not found for '${node_name}' in ${workflow_path}" >&2
    exit 1
  fi

  if grep -Fq "{{" <<<"$query"; then
    echo "Raw SQL interpolation detected in '${node_name}' for ${workflow_path}" >&2
    exit 1
  fi

  if [[ -z "$query_replacement" || "$query_replacement" == "null" ]]; then
    echo "Missing queryReplacement for '${node_name}' in ${workflow_path}" >&2
    exit 1
  fi

  replacement_count="$(count_n8n_query_replacement_bindings "$query_replacement" "$node_name" "$workflow_path")"
  normalized_query="$(strip_sql_noncode <<<"$query")"
  max_placeholder="$(grep -oE '\$[0-9]+' <<<"$normalized_query" | tr -d '$' | sort -n | tail -1 || true)"

  if [[ -n "$max_placeholder" && "$replacement_count" -lt "$max_placeholder" ]]; then
    echo "queryReplacement provides ${replacement_count} binding(s), but '${node_name}' query references up to \$${max_placeholder} in ${workflow_path}" >&2
    exit 1
  fi

  for pattern in "$@"; do
    if [[ "$pattern" =~ ^\$([0-9]+)$ ]]; then
      local idx
      local placeholder_regex
      idx="${BASH_REMATCH[1]}"
      printf -v placeholder_regex '(^|[^0-9])\\$%s([^0-9]|$)' "$idx"
      if ! grep -Eq "$placeholder_regex" <<<"$normalized_query"; then
        echo "Missing '${pattern}' in '${node_name}' query for ${workflow_path}" >&2
        exit 1
      fi
    elif ! grep -Fq -- "$pattern" <<<"$normalized_query"; then
      echo "Missing '${pattern}' in '${node_name}' query for ${workflow_path}" >&2
      exit 1
    fi
  done
}

require_internal_http_json_node() {
  local workflow_path="$1"
  local node_name="$2"
  local expected_url="$3"
  local require_tenant_header="$4"
  shift 4

  local matched_nodes
  local match_count
  local node_type
  local method
  local url
  local headers
  local json_body
  matched_nodes="$(jq -c --arg node_name "$node_name" '[.nodes[] | select(.name == $node_name)]' "$workflow_path")"
  match_count="$(jq -r 'length' <<<"$matched_nodes")"

  if [[ "$match_count" -ne 1 ]]; then
    echo "Expected exactly 1 node named '${node_name}' in ${workflow_path}, found ${match_count}" >&2
    exit 1
  fi

  node_type="$(jq -r '.[0].type' <<<"$matched_nodes")"
  method="$(jq -r '.[0].parameters.method // empty' <<<"$matched_nodes")"
  url="$(jq -r '.[0].parameters.url' <<<"$matched_nodes")"
  headers="$(jq -c '.[0].parameters.headerParameters.parameters // []' <<<"$matched_nodes")"
  json_body="$(jq -r '.[0].parameters.jsonBody' <<<"$matched_nodes")"

  if [[ "$node_type" != "n8n-nodes-base.httpRequest" ]]; then
    echo "Expected '${node_name}' to be an HTTP request in ${workflow_path}, found ${node_type}" >&2
    exit 1
  fi

  if [[ "$method" != "POST" ]]; then
    echo "Expected '${node_name}' to use POST in ${workflow_path}, found ${method:-<unset>}" >&2
    exit 1
  fi

  if [[ "$url" != "$expected_url" ]]; then
    echo "URL mismatch for '${node_name}' in ${workflow_path}: expected ${expected_url}" >&2
    exit 1
  fi

  if ! grep -Fq "X-API-Key" <<<"$headers"; then
    echo "'${node_name}' must forward X-API-Key in ${workflow_path}" >&2
    exit 1
  fi

  if ! grep -Fq "POLICY_BUNDLE_INTERNAL_API_KEY" <<<"$headers"; then
    echo "'${node_name}' must source X-API-Key from workflow environment in ${workflow_path}" >&2
    exit 1
  fi

  if [[ "$require_tenant_header" == "true" ]] && ! grep -Fq "X-Authenticated-Tenant-Id" <<<"$headers"; then
    echo "'${node_name}' must forward X-Authenticated-Tenant-Id in ${workflow_path}" >&2
    exit 1
  fi

  if [[ -z "$json_body" || "$json_body" == "null" ]]; then
    echo "JSON body not found for '${node_name}' in ${workflow_path}" >&2
    exit 1
  fi

  for pattern in "$@"; do
    if ! grep -Fq -- "$pattern" <<<"$json_body"; then
      echo "Missing '${pattern}' in '${node_name}' request body for ${workflow_path}" >&2
      exit 1
    fi
  done
}

check_policy_registry_workflows() {
  local workflow_path="n8n/workflows-v3/$1"
  local primary_node_type

  if [[ ! -f "$workflow_path" ]]; then
    echo "Workflow file not found: ${workflow_path}" >&2
    exit 1
  fi

  case "$1" in
    06_policy_registry_upsert.json) primary_node_type="$(jq -r '.nodes[] | select(.name == "Upsert Workflow Rule") | .type' "$workflow_path")" ;;
    07_policy_registry_publish.json) primary_node_type="$(jq -r '.nodes[] | select(.name == "Publish Revision") | .type' "$workflow_path")" ;;
    09_policy_registry_get.json) primary_node_type="$(jq -r '.nodes[] | select(.name == "Get Workflow Rule") | .type' "$workflow_path")" ;;
    11_policy_candidate_seed.json) primary_node_type="$(jq -r '.nodes[] | select(.name == "Insert Seed Episode") | .type' "$workflow_path")" ;;
    12_policy_registry_delete.json) primary_node_type="$(jq -r '.nodes[] | select(.name == "Delete Workflow Rule") | .type' "$workflow_path")" ;;
    *)
      echo "Unhandled workflow fixture: $1" >&2
      exit 1
      ;;
  esac

  case "$1" in
    06_policy_registry_upsert.json)
      if [[ "$primary_node_type" == "n8n-nodes-base.httpRequest" ]]; then
        require_internal_http_json_node \
          "$workflow_path" "Upsert Workflow Rule" "http://policy-bundle-server:8088/internal/tenant-data/policy/workflow/upsert" "false" \
          "workflow_id" "task_type" "tenant_id" "scope_pattern" "constraints" "enabled"
        require_internal_http_json_node \
          "$workflow_path" "Insert Upsert Log" "http://policy-bundle-server:8088/internal/tenant-data/policy/publish-log" "false" \
          "revision_id" "action" "actor" "result" "details_jsonb"
      else
        require_parameterized_query "$workflow_path" "Upsert Workflow Rule" '$1' '$2' '$3' '$4' '$5::jsonb' '$6'
        require_parameterized_query "$workflow_path" "Insert Upsert Log" '$1' '$2::jsonb'
      fi
      ;;
    07_policy_registry_publish.json)
      if [[ "$primary_node_type" == "n8n-nodes-base.httpRequest" ]]; then
        require_internal_http_json_node \
          "$workflow_path" "Publish Revision" "http://policy-bundle-server:8088/internal/tenant-data/policy/revision/publish" "false" \
          "revision_id" "notes" "actor"
        require_internal_http_json_node \
          "$workflow_path" "Insert Publish Log" "http://policy-bundle-server:8088/internal/tenant-data/policy/publish-log" "false" \
          "revision_id" "action" "actor" "result" "details_jsonb"
        require_internal_http_json_node \
          "$workflow_path" "Load Published Payload" "http://policy-bundle-server:8088/internal/tenant-data/policy/revision/payload" "false" \
          "revision_id"
      else
        require_parameterized_query "$workflow_path" "Publish Revision" '$1' '$2' '$3' '$4'
        require_parameterized_query "$workflow_path" "Insert Publish Log" '$1' '$2' '$3::jsonb'
        require_parameterized_query "$workflow_path" "Load Published Payload" '$1'
      fi
      ;;
    09_policy_registry_get.json)
      if [[ "$primary_node_type" == "n8n-nodes-base.httpRequest" ]]; then
        require_internal_http_json_node \
          "$workflow_path" "Get Workflow Rule" "http://policy-bundle-server:8088/internal/tenant-data/policy/workflow/get" "false" \
          "workflow_id" "task_type"
      else
        require_parameterized_query "$workflow_path" "Get Workflow Rule" '$1' '$2'
      fi
      ;;
    11_policy_candidate_seed.json)
      if [[ "$primary_node_type" == "n8n-nodes-base.httpRequest" ]]; then
        require_internal_http_json_node \
          "$workflow_path" "Insert Seed Episode" "http://policy-bundle-server:8088/internal/tenant-data/policy/candidate-event" "true" \
          "task_type" "tenant_id" "scope" "source"
      else
        require_parameterized_query "$workflow_path" "Insert Seed Episode" '$1' '$2' '$3' '$4'
      fi
      ;;
    12_policy_registry_delete.json)
      if [[ "$primary_node_type" == "n8n-nodes-base.httpRequest" ]]; then
        require_internal_http_json_node \
          "$workflow_path" "Delete Workflow Rule" "http://policy-bundle-server:8088/internal/tenant-data/policy/workflow/delete" "false" \
          "workflow_id" "task_type" "tenant_id" "scope_pattern"
        require_internal_http_json_node \
          "$workflow_path" "Insert Delete Log" "http://policy-bundle-server:8088/internal/tenant-data/policy/publish-log" "false" \
          "revision_id" "action" "actor" "result" "details_jsonb"
      else
        require_parameterized_query "$workflow_path" "Delete Workflow Rule" '$1' '$2' '$3' '$4'
        require_parameterized_query "$workflow_path" "Insert Delete Log" '$1' '$2::jsonb'
      fi
      ;;
    *)
      echo "Unhandled workflow fixture: $1" >&2
      exit 1
      ;;
  esac
}

check_policy_registry_workflows "06_policy_registry_upsert.json"
check_policy_registry_workflows "07_policy_registry_publish.json"
check_policy_registry_workflows "09_policy_registry_get.json"
check_policy_registry_workflows "11_policy_candidate_seed.json"
check_policy_registry_workflows "12_policy_registry_delete.json"

echo "Policy registry workflow SQL checks passed."
