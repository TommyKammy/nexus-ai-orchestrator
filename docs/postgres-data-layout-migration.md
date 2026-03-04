# PostgreSQL Data Layout Migration (Host Runtime)

## Why this exists
Some host environments can fail PostgreSQL startup after compose updates if runtime data layout differs from expected `PGDATA` mount structure.

Typical error:

```text
initdb: error: directory "/var/lib/postgresql/data" exists but is not empty
```

## Target layout
- Runtime path should be consistent with compose PGDATA expectations.
- For this repository, runtime data is expected under `./postgres` (or `./postgres/data` for migrated legacy environments).

## Recommended migration command
Run on host repository root:

```bash
cd /opt/ai-orchestrator
./scripts/migrate-postgres-data-layout.sh
```

What the script does:
1. Detects legacy `./postgres/PG_VERSION` layout
2. Stops PostgreSQL container
3. Creates backup under `backups/postgres-layout-migration/<timestamp>/`
4. Moves data to `./postgres/data`
5. Restarts PostgreSQL and verifies readiness

## Safety notes
- Script is idempotent for already-migrated environments.
- Keep filesystem backup and logical backup (`pg_dump`) before any migration.

## Quick checks

```bash
docker exec ai-postgres pg_isready -U ai_user
ls -la /opt/ai-orchestrator/postgres
ls -la /opt/ai-orchestrator/postgres/data
```
