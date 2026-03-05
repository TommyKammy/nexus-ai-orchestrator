# Rollback and DR Runbook

## Purpose

Define a single operational playbook for rollback and DR decisions across compose and k8s deployments.

## Targets

- RTO target: 30 minutes for compose service recovery, 45 minutes for k8s namespace workload recovery.
- RPO target: 15 minutes (backup interval or last successful dump).

## Trigger Conditions

Rollback is triggered when one or more conditions are met:
- Release introduces user-facing errors that are not mitigated within 10 minutes.
- Health checks fail for critical paths (`n8n`, `postgres`, `redis`, policy endpoint).
- Data/schema migration causes workflow execution failures.

DR switch is triggered when one or more conditions are met:
- Primary node/cluster outage is expected to exceed RTO.
- Storage/network fault prevents restore on primary in RTO window.
- Security incident requires host/cluster isolation.

## Script Mapping and Preconditions

### `scripts/n8n-upgrade-backup.sh`

Use before any n8n or compose upgrade.

Preconditions:
- Run from `/opt/ai-orchestrator`.
- `docker compose` and `postgres` container are healthy.
- Sufficient disk for SQL + `n8n` tar archive.

Cautions:
- Stops `n8n` during backup for consistency.
- Produces backup directory under `./backups/n8n-upgrade-*`.

### `scripts/n8n-rollback.sh <backup-directory>`

Use when upgrade rollback is required.

Preconditions:
- Backup directory from `n8n-upgrade-backup.sh` exists.
- Operator confirms data restore point is correct.

Cautions:
- Drops and recreates `ai_memory` database.
- Restores `docker-compose.yml` from backup.
- Must validate workflows and webhooks post-restore.

### `scripts/deploy-executor-production.sh`

Use for executor deployment and automated rollback on failed health checks.

Preconditions:
- Docker + Docker Compose available.
- Privilege for monitoring/logrotate setup where needed.

Cautions:
- Creates backup under `backups/executor-*` unless `--skip-backup`.
- Writes/updates host-level settings (cron entry, `/etc/logrotate.d/executor-monitor`, and possibly `/etc/docker/daemon.json`).
- `rollback()` restores only `executor/` from latest backup and restarts executor; it does not restore all backup artifacts automatically.

## Recovery Procedures

## 1) Compose Rollback Path

1. Select a known-good backup created before the failed change.
2. Roll back from selected backup:
```bash
bash scripts/n8n-rollback.sh ./backups/n8n-upgrade-YYYYMMDD-HHMMSS
```
3. Verify:
```bash
docker compose ps
curl -fsS http://127.0.0.1:8181/health
# n8n readiness from n8n network namespace
docker run --rm --network container:ai-n8n curlimages/curl:8.10.1 -fsS http://localhost:5678/healthz/readiness
```
4. If no known-good backup exists, stop and escalate incident command instead of creating a new backup from potentially broken state.

## 2) K8s Recovery Path

1. Confirm namespace and workload status:
```bash
kubectl get ns executor-system
kubectl -n executor-system get deploy,pods
```
2. Recover workload-level failures with rollout restart:
```bash
kubectl -n executor-system rollout restart deployment/<name>
kubectl -n executor-system rollout status deployment/<name> --timeout=180s
```
3. For image regression, roll back deployment revision:
```bash
kubectl -n executor-system rollout undo deployment/<name>
```
4. Re-run smoke checks:
```bash
bash scripts/ci/k8s_smoke_test.sh
```

## 3) DR Switch Path (Primary -> Secondary)

1. Declare incident commander and freeze deploys.
2. Restore DB + n8n backup on secondary environment.
3. Deploy compose/k8s manifests on secondary.
4. Run health checks + smoke checks.
5. Flip traffic/DNS after validation.
6. Record final Go/No-Go in DR report.

## Health Check Baseline

Compose:
- `docker compose ps`
- n8n readiness (`/healthz/readiness` via `container:ai-n8n`)
- OPA health (`http://127.0.0.1:8181/health`)

K8s:
- `kubectl -n executor-system get deploy,pods`
- rollout status for target deployment(s)

## Evidence

- Drill report: `docs/reports/dr-drill-20260305.md`
