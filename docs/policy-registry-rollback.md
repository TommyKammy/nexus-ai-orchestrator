# Policy Registry Rollback Guide

## When to rollback
- Incorrect deny/allow behavior after publish
- Unexpected broad allow-list entries
- Wrong workflow/task mapping in published revision

## Rollback strategy
Rollback is performed by re-publishing the previous known-good policy set.
No OPA restart is required.

## Procedure

### 1) Identify current and previous revisions
Run SQL against `policy_revisions` ordered by `published_at` desc.
Find:
- current active revision
- previous known-good revision

### 2) Re-publish previous revision payload
Option A (recommended):
- Extract `payload_jsonb.workflows` from previous revision
- Upsert those rows into `policy_workflows`
- Publish with new rollback revision id (example: `rev-rollback-20260222-01`)

Option B:
- Directly call bundle publish endpoint with previous workflows payload

### 3) Confirm rollback reflection
- `GET /registry/current` should show rollback revision
- OPA decision check should return expected allow/deny

### 4) Audit record
Store incident metadata in `policy_publish_logs` notes/details:
- reason
- operator
- ticket id
- affected workflows/task types

## Safety checks
- Always test rollback in test scope before production scope if possible.
- Never delete historical revisions.
- Keep rollback payload immutable in incident records.
