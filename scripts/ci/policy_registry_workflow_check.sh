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
      escape = 0

      for (i = 1; i <= length(expr); i++) {
        ch = substr(expr, i, 1)

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
      if (array_depth != 0 || brace_depth != 0 || paren_depth != 0) {
        fail("queryReplacement has unbalanced delimiters")
      }

      print count
    }
  ' <<<"$query_replacement"
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
  max_placeholder="$(grep -oE '\$[0-9]+' <<<"$query" | tr -d '$' | sort -n | tail -1 || true)"

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
      if ! grep -Eq "$placeholder_regex" <<<"$query"; then
        echo "Missing '${pattern}' in '${node_name}' query for ${workflow_path}" >&2
        exit 1
      fi
    elif ! grep -Fq -- "$pattern" <<<"$query"; then
      echo "Missing '${pattern}' in '${node_name}' query for ${workflow_path}" >&2
      exit 1
    fi
  done
}

check_policy_registry_workflows() {
  local workflow_path="n8n/workflows-v3/$1"

  if [[ ! -f "$workflow_path" ]]; then
    echo "Workflow file not found: ${workflow_path}" >&2
    exit 1
  fi

  case "$1" in
    06_policy_registry_upsert.json)
      require_parameterized_query "$workflow_path" "Upsert Workflow Rule" '$1' '$2' '$3' '$4' '$5::jsonb' '$6'
      require_parameterized_query "$workflow_path" "Insert Upsert Log" '$1' '$2::jsonb'
      ;;
    07_policy_registry_publish.json)
      require_parameterized_query "$workflow_path" "Publish Revision" '$1' '$2' '$3' '$4'
      require_parameterized_query "$workflow_path" "Insert Publish Log" '$1' '$2' '$3::jsonb'
      require_parameterized_query "$workflow_path" "Load Published Payload" '$1'
      ;;
    09_policy_registry_get.json)
      require_parameterized_query "$workflow_path" "Get Workflow Rule" '$1' '$2'
      ;;
    11_policy_candidate_seed.json)
      require_parameterized_query "$workflow_path" "Insert Seed Episode" '$1' '$2' '$3' '$4'
      ;;
    12_policy_registry_delete.json)
      require_parameterized_query "$workflow_path" "Delete Workflow Rule" '$1' '$2' '$3' '$4'
      require_parameterized_query "$workflow_path" "Insert Delete Log" '$1' '$2::jsonb'
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
