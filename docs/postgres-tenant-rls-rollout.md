# PostgreSQL Tenant RLS Rollout

This repository now treats `memory_vectors` and `memory_episodes` as tenant-isolated tables enforced by PostgreSQL row-level security (RLS).

## What Changed

- `sql/20260412_tenant_row_level_security.sql` creates `memory_episodes` if needed.
- The same migration enables and forces RLS on:
  - `memory_vectors`
  - `memory_episodes`
- Access policies are bound to `app_current_tenant_id()`, which reads `app.current_tenant_id` from the current PostgreSQL session.
- Workflow queries that read or write those tables now set `app.current_tenant_id` in the same SQL statement with `set_config(..., true)`.

## Operator Expectations

Run the schema helper after deploying the updated workflows:

```bash
POSTGRES_PASSWORD=... bash scripts/apply-memory-audit-migration.sh
```

RLS only protects tenant-facing tables when the caller sets tenant context before the statement runs.

Required session contract:

```sql
SELECT set_config('app.current_tenant_id', '<tenant-id>', true);
```

In this repository, the n8n Postgres nodes set that context inline with the tenant-scoped query.

## Verification

Expected same-tenant access pattern:

```sql
BEGIN;
SELECT set_config('app.current_tenant_id', 'tenant-a', true);
SELECT COUNT(*) FROM memory_vectors WHERE tenant_id = 'tenant-a';
COMMIT;
```

Expected cross-tenant denial pattern:

```sql
BEGIN;
SELECT set_config('app.current_tenant_id', 'tenant-a', true);
SELECT COUNT(*) FROM memory_vectors WHERE tenant_id = 'tenant-b';
COMMIT;
```

The second query must return zero visible rows under RLS, even if the application query omits or weakens a tenant predicate elsewhere in the statement.

## Rollback Considerations

- Removing the workflow-side `set_config` calls while leaving RLS enabled will cause tenant table reads and writes to fail or return no rows.
- Disabling RLS removes the database-enforced tenant isolation guardrail and should be treated as a security rollback.
