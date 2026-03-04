# Contributing

## Branch and PR workflow

1. Create a task-focused branch from `main`:
   - Example: `codex/<topic>` or `feature/<topic>`
2. Implement one clear objective per PR.
3. Open a PR and request human review.
4. Merge only after approval and checks pass.

Direct pushes to `main` are not allowed.

## Required verification before merge

```bash
pnpm -r --if-present lint
pnpm -r --if-present typecheck
pnpm -r --if-present test
pnpm -r --if-present build
pnpm e2e
```

## Security and scope expectations

- Do not bypass auth/authz controls.
- Do not commit secrets or credentials.
- Keep changes tightly scoped to the task.
- Document risks and rollback in each PR description.

Run a quick secret scan before opening a PR:

```bash
grep -r "CHANGE_ME\\|password\\|secret" . --include="*.yml" --include="*.yaml" --include="*.py" --include="*.ts" --include="*.js"
```
