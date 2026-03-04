# Contributing

## Branch and PR workflow

1. Create a task-focused branch from `main`:
   - Example: `codex/<topic>` or `feature/<topic>`
2. Implement one clear objective per PR.
3. Open a PR and request human review.
4. Merge only after approval and checks pass.

Direct pushes to `main` are not allowed.

## Required verification before merge

Use the same checks that currently run in GitHub Actions:

```bash
docker run --rm -v "$PWD/policy/opa:/policy" openpolicyagent/opa:0.68.0 \
  check /policy/authz.rego /policy/risk.rego
docker run --rm -v "$PWD/policy/opa:/policy" openpolicyagent/opa:0.68.0 \
  eval --data /policy --input /policy/example_input.json "data.ai.policy.result"
python3 -m py_compile executor/api_server.py executor/policy_client.py executor/run_task.py
python3 scripts/validate_slack_workflows.py n8n/workflows-v3
bash scripts/ci/n8n_import_test.sh
```

Note: root-level `pnpm e2e` and `pnpm -r --if-present <script>` are not valid in this repository until a root workspace/package manifest is introduced.

## Security and scope expectations

- Do not bypass auth/authz controls.
- Do not commit secrets or credentials.
- Keep changes tightly scoped to the task.
- Document risks and rollback in each PR description.

Run a quick secret scan before opening a PR:

```bash
grep -r "CHANGE_ME\\|password\\|secret" . --include="*.yml" --include="*.yaml" --include="*.py" --include="*.ts" --include="*.js"
```
