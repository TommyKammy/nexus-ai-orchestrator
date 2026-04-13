## Summary

- What changed
- Why it changed

## Verification

Run and paste results:

```bash
bash scripts/ci/regression.sh
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
- [ ] Governance-sensitive `policy`/CI/CODEOWNERS changes have two human approvals
- [ ] No secrets or credentials added
