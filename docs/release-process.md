# Release Process

## SemVer Rule

- Tag format: `vMAJOR.MINOR.PATCH`
- Use:
  - MAJOR: breaking changes
  - MINOR: backward-compatible features
  - PATCH: backward-compatible fixes

## Release Workflow

- Workflow file: `.github/workflows/release.yml`
- Triggers:
  - `push` tag matching `v*.*.*`
  - `workflow_dispatch` with inputs:
    - `release_tag`
    - `dry_run`

## Standard Release Cut

1. Ensure `main` is green.
2. Create and push release tag:

```bash
git checkout main
git pull --ff-only origin main
git tag -a v1.0.0 -m "v1.0.0"
git push origin v1.0.0
```

3. Confirm GitHub Actions `Release` workflow succeeded.
4. Confirm GitHub Release page contains generated notes artifact/body.

## Dry-run Procedure

Use workflow dispatch with:
- `release_tag=v1.0.0`
- `dry_run=true`

Expected result:
- Workflow generates `RELEASE_NOTES.md` artifact.
- No GitHub Release object is created.

## Rollback / Recovery

If an incorrect tag is pushed:

```bash
git tag -d v1.0.0 || true
git push origin :refs/tags/v1.0.0
```

Then re-create the correct tag and re-run release.
