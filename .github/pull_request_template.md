## Summary

- What changed
- Why it changed

## Verification

Run and paste results:

```bash
pnpm -r --if-present lint
pnpm -r --if-present typecheck
pnpm -r --if-present test
pnpm -r --if-present build
pnpm e2e
```

Additional project checks (if applicable):

```bash
# OPA policy validation
# n8n workflow validation/import
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
