# ADR-002: Tenancy and Data Isolation Model

- Status: Accepted
- Date: 2026-03-04
- Related Issue: #2
- Supersedes: None
- Depends on: ADR-001

## Context

`nexus-ai-orchestrator` executes untrusted code and stores policy/audit/memory data for multiple logical tenants. Tenant isolation must remain correct across:

- API input handling (`executor/api_server.py`)
- policy evaluation (`policy/opa/*.rego`)
- workflow orchestration (`n8n/workflows*`)
- persistence layers (PostgreSQL, Redis)

Existing implementation already carries `tenant_id` and `scope` through key execution paths, but the expected model is not formally documented.

## Decision

Adopt a two-key tenancy model:

1. `tenant_id`: coarse isolation boundary (organization/workspace/account)
2. `scope`: fine-grained isolation boundary inside tenant (project/user/workflow/domain)

All runtime actions MUST be evaluated and stored under both keys unless explicitly marked as control-plane operations.

## Data Classification

- `Tenant data`: execution payload metadata, session metadata, memory vectors, audit records, policy candidate events.
- `Control-plane data`: policy definitions, policy revisions, operational metadata.

Control-plane records may use wildcard patterns where needed for policy authoring, but tenant-facing execution and data reads/writes must be bound to explicit `tenant_id` + `scope`.

## Isolation Rules

1. API boundary
- `executor.execute` requires `tenant_id`, `scope`, and `code`.
- `executor.session.create` requires `tenant_id` and `scope`.
- `executor.session.execute` must derive `tenant_id` and `scope` from session metadata.

2. Policy boundary
- Policy input must include subject and resource tenancy attributes.
- `subject.scope` and `resource.scope` mismatch is denied.
- Missing tenancy attributes must be treated as deny for execution actions (enforcement follow-up).

3. Data boundary
- Writes must include tenancy keys where data is tenant-facing.
- Reads must filter by `tenant_id` and `scope` (or a documented, constrained pattern rule).
- Cross-tenant joins/queries are forbidden on request paths.

4. Session/cache boundary
- Session metadata is authoritative for subsequent session execution tenancy.
- Cache keys must include tenancy dimensions (`tenant_id`, `scope`) to avoid cross-tenant collisions.

## Wildcard and Pattern Policy

- `*` wildcard is allowed only for control-plane policy registry records (`policy_workflows`, `policy_candidate_events`) and must not be used to bypass execution tenancy checks.
- Pattern matching (`scope_pattern`) is policy authoring metadata, not execution identity.
- Runtime execution decisions must still resolve to concrete `tenant_id` + `scope`.

## Storage Mapping (Current)

- `policy_workflows`: `tenant_id`, `scope_pattern` (policy config)
- `policy_candidate_events`: `tenant_id`, `scope` (candidate telemetry)
- `audit_events`: append-only; tenancy should be persisted by writer path
- session metadata: carries `tenant_id` and `scope` for `session.execute`

## Security Invariants

- A request for one `tenant_id` must never access another tenant's data.
- Scope mismatch between caller and resource must be denied.
- Missing tenancy identity on execution path is invalid.
- Wildcards are never a substitute for concrete runtime tenant identity.

## Known Gaps and Required Follow-ups

1. Add explicit deny rules in OPA when required tenant keys are missing on execution/session actions.
2. Add automated tests for:
- missing `tenant_id`
- missing `scope`
- cross-tenant/session misuse attempts
3. Ensure all tenant-facing tables have explicit tenancy columns and indexed filter paths.
4. Document Redis key format to include tenant dimensions consistently.

## Consequences

### Positive

- Clear, testable tenancy contract across API, policy, and data layers.
- Lower risk of cross-tenant data leakage.
- Better auditability and incident triage.

### Trade-offs

- Additional schema and validation constraints increase implementation effort.
- More strict validation may reject currently tolerated malformed requests.

## Verification Guidance

- API tests proving tenancy-required fields are enforced.
- Policy tests proving scope mismatch and missing-key behavior.
- Query reviews confirming tenant/scope predicates in tenant-facing reads.
