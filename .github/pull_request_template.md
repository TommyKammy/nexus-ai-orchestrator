## Summary

- What changed
- Why it changed

## Verification

Run and paste results:

```bash
docker run --rm -v "$PWD/policy/opa:/policy" openpolicyagent/opa:0.68.0 \
  check /policy/authz.rego /policy/risk.rego
docker run --rm -v "$PWD/policy/opa:/policy" openpolicyagent/opa:0.68.0 \
  eval --data /policy --input /policy/example_input.json "data.ai.policy.result"
python3 -m py_compile executor/api_server.py executor/policy_client.py executor/run_task.py
python3 scripts/validate_slack_workflows.py n8n/workflows-v3
bash scripts/ci/n8n_import_test.sh
```

Additional project checks (if applicable):

```bash
# compose or k8s smoke checks
```

## Risks / Known Gaps

- Potential impact areas
- Known limitations

## Rollback Plan

- Exact rollback steps (revert commit/PR, infra rollback, migration rollback)

## Checklist

- [ ] Scope is focused to one objective
- [ ] No direct push to `main`
- [ ] Security-sensitive changes reviewed
- [ ] No secrets or credentials added
