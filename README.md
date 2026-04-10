# Nexus AI Orchestrator

Secure AI orchestration infrastructure with n8n workflows, policy evaluation, semantic memory, and isolated executor runtime.

## What This Repo Provides

- Workflow orchestration with `n8n`
- Semantic memory and audit persistence on PostgreSQL + pgvector
- Policy decision point with OPA
- Redis-backed state/cache
- Hardened edge routing with Caddy
- Executor runtime path for isolated task execution
- Compose and Kubernetes operational paths

## Core Stack

- `postgres` (`pgvector/pgvector:pg18`)
- `redis` (`redis:8.6-alpine`)
- `n8n` (`n8nio/n8n:2.8.3`)
- `opa` (`openpolicyagent/opa:0.68.0`)
- `policy-bundle-server` (local image)
- `caddy` (local image)
- `executor` (`python:3.11-slim`, isolated task execution runtime)

Primary compose file: `docker-compose.yml`

Additional validated compose variants:

- `docker-compose.executor.yml`: executor-focused stack for running isolated tasks without the full orchestration surface.
- `docker-compose.n8n-ja.yml`: n8n stack preconfigured for Japanese locale/regionalization.

## Quick Start (Compose)

```bash
git clone https://github.com/TommyKammy/nexus-ai-orchestrator.git
cd nexus-ai-orchestrator
cp .env.example .env
# edit .env and replace all CHANGE_ME values

bash scripts/bootstrap-local.sh
```

Alternative deploy flow (server-oriented scripts):

```bash
./deploy.sh
```

Important: do not run local bootstrap and deploy flow at the same time on the same host.

## Required Environment Variables

At minimum configure these in `.env`:

- `POSTGRES_PASSWORD`
- `N8N_ENCRYPTION_KEY`
- `N8N_BASIC_AUTH_PASSWORD`
- `N8N_WEBHOOK_API_KEY`
- `SLACK_INTERNAL_AUTH`
- `N8N_HOST`

Reference: `.env.example`

Policy enforcement defaults to `POLICY_MODE=enforce` and `POLICY_FAIL_MODE=closed`. Development-only advisory or fail-open overrides require explicit `POLICY_ALLOW_UNSAFE=true`.

## Common Commands

```bash
# CI-equivalent local gates
pnpm -r --if-present lint
pnpm -r --if-present typecheck
pnpm -r --if-present test
pnpm -r --if-present build

# e2e (import test + compose core journey)
pnpm e2e

# core journey only
pnpm e2e:compose-core

# full regression entrypoint
bash scripts/ci/regression.sh
```

## Kubernetes Path

See `k8s/README.md` for deployment and verification.

Key manifest groups:

- `k8s/config/crd/`
- `k8s/config/deployment/`
- `k8s/controllers/`

K8s CI/load checks:

- `scripts/ci/k8s_smoke_test.sh`
- `scripts/ci/k8s_load_test.sh`

## CI Workflows

- `.github/workflows/quality-gates.yml`
- `.github/workflows/validate-workflows.yml`
- `.github/workflows/policy-tests.yml`
- `.github/workflows/security-audit.yml`
- `.github/workflows/k8s-smoke-load.yml`
- `.github/workflows/release.yml`

## Release Process

- SemVer release/tag flow: `docs/release-process.md`
- Release workflow trigger:
  - tag push: `v*.*.*`
  - manual dry-run: `workflow_dispatch`

## Security and Operations

- Security baseline: `SECURITY.md`
- Threat model: `docs/security-threat-model-v1.md`
- Security audit report: `docs/reports/security-audit-report-20260305.md`
- Rollback/DR runbook: `docs/rollback-dr-runbook.md`
- DR drill evidence: `docs/reports/dr-drill-20260305.md`
- Production readiness checklist: `docs/production-readiness-checklist.md`
- Production sign-off record: `docs/reports/production-readiness-signoff-20260305.md`

## Data/Runtime Upgrade Utilities

- PostgreSQL 16 -> 18: `scripts/upgrade-postgres-16-to-18.sh`
- Redis 7 -> 8: `scripts/upgrade-redis-7-to-8.sh`
- n8n backup/rollback:
  - `scripts/n8n-upgrade-backup.sh`
  - `scripts/n8n-rollback.sh`

## Repository Map

- `docs/` design, runbooks, and reports
- `executor/` executor runtime code
- `k8s/` manifests/controllers
- `n8n/workflows/` legacy workflows (still schema-validated in CI; no new workflows here)
- `n8n/workflows-v3/` canonical v3 workflow definitions
- `policy/` OPA policy source/runtime
- `scripts/` operational and CI helper scripts

## Contributing

See `CONTRIBUTING.md`.

## License

MIT
