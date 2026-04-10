#!/usr/bin/env bash
set -euo pipefail

repo="${GITHUB_REPOSITORY:-TommyKammy/nexus-ai-orchestrator}"
branch="${GITHUB_BRANCH:-main}"

required_contexts=(
  "Quality Gates / quality-gates"
  "Validate workflows / validate"
  "Validate workflows / import-test"
  "Policy Tests / policy-and-executor"
  "Security Audit / security-audit"
)

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

if ! protection_json="$(gh api "repos/${repo}/branches/${branch}/protection" 2>/dev/null)"; then
  echo "Branch protection policy check failed:" >&2
  echo "- unable to read branch protection for ${repo}:${branch} (verify branch exists and gh auth/token scopes)" >&2
  exit 1
fi

required_status_read_failed=0
if ! required_status_json="$(
  gh api "repos/${repo}/branches/${branch}/protection/required_status_checks" 2>/dev/null
)"; then
  required_status_json=""
  required_status_read_failed=1
fi

expected_contexts_json="$(printf '%s\n' "${required_contexts[@]}" | python3 -c 'import json, sys; print(json.dumps([line.strip() for line in sys.stdin if line.strip()]))')"

python3 - "$protection_json" "$required_status_json" "$expected_contexts_json" "$required_status_read_failed" <<'PY'
import json
import sys

protection = json.loads(sys.argv[1])
required_status = json.loads(sys.argv[2]) if sys.argv[2] else None
expected_contexts = json.loads(sys.argv[3])
required_status_read_failed = sys.argv[4] == "1"

errors = []
warnings = []

reviews = protection.get("required_pull_request_reviews") or {}
if reviews.get("required_approving_review_count", 0) < 1:
    errors.append("required_approving_review_count must be at least 1")

if not protection.get("enforce_admins", {}).get("enabled", False):
    errors.append("enforce_admins must be enabled")

if protection.get("allow_force_pushes", {}).get("enabled", True):
    errors.append("force pushes must be disabled")

if protection.get("allow_deletions", {}).get("enabled", True):
    errors.append("branch deletions must be disabled")

if not protection.get("required_conversation_resolution", {}).get("enabled", False):
    errors.append("required conversation resolution must be enabled")

if required_status_read_failed:
    errors.append("unable to read required status checks (verify gh auth/token scopes)")
elif not required_status:
    errors.append("required status checks are not enabled")
else:
    if not required_status.get("strict", False):
        errors.append("required status checks must require branches to be up to date")

    actual_contexts = sorted(required_status.get("contexts") or [])
    missing_contexts = [context for context in expected_contexts if context not in actual_contexts]
    extra_contexts = [context for context in actual_contexts if context not in expected_contexts]

    if missing_contexts:
        errors.append(f"missing required status checks: {', '.join(missing_contexts)}")
    if extra_contexts:
        warnings.append(f"additional required status checks present: {', '.join(extra_contexts)}")

if errors:
    print("Branch protection policy check failed:", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    sys.exit(1)

for warning in warnings:
    print(f"Branch protection policy check warning: {warning}", file=sys.stderr)

print("Branch protection policy matches the documented main-branch requirements.")
PY
