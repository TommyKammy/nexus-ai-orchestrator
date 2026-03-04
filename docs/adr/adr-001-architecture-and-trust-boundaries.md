# ADR-001: Architecture and Trust Boundaries

- Status: Accepted
- Date: 2026-03-04
- Related Issue: #1

## Context

`nexus-ai-orchestrator` combines edge routing, workflow orchestration, policy evaluation, code execution sandboxing, and persistent memory.

Primary runtime components:

- `Caddy`: public edge, TLS termination, webhook ingress control.
- `n8n`: orchestration entry point for workflows.
- `OPA` and `policy-bundle-server`: policy decision and runtime policy publication.
- `Executor API` and sandbox containers: code execution path.
- `PostgreSQL (pgvector)` and `Redis`: persistence, memory retrieval, session/cache state.

This architecture introduces multiple trust transitions and high-risk paths, especially between user-originated requests and code execution.

## Decision

Adopt a control-plane architecture with explicit trust boundaries and a default-deny posture for execution.

### System Context

```text
Untrusted Clients
   |
   | HTTPS
   v
[TB-1] Caddy (Edge Boundary)
   |
   | Internal service network only
   v
[TB-2] n8n (Orchestration Boundary)
   |            |              |
   | policy     | persistence  | execution request
   v            v              v
[TB-3] OPA   [TB-5] Postgres  [TB-4] Executor API -> Sandbox Containers
   ^            ^                   |
   |            |                   v
   +------------+--------------- [TB-5] Redis
```

### Trust Boundaries

- `TB-1 Edge Boundary`: Internet to Caddy. All inbound requests are untrusted.
- `TB-2 Orchestration Boundary`: Caddy to n8n. Only authenticated and routed requests are accepted.
- `TB-3 Policy Boundary`: n8n/Executor to OPA. Policy decisions are authoritative and auditable.
- `TB-4 Execution Boundary`: Executor API to ephemeral sandbox containers. Code is always untrusted.
- `TB-5 Data Boundary`: Service layer to PostgreSQL/Redis. Data integrity and tenant scope must be enforced.

### Required Rules by Boundary

1. `TB-1`
- Terminate TLS at edge.
- Enforce webhook authentication and request size/rate limits.
- Never expose internal executor endpoints publicly.

2. `TB-2`
- Treat workflow input as untrusted until validated.
- Apply schema and tenant/scope validation before policy and execution.
- Preserve request identity (`X-Request-ID`) for traceability.

3. `TB-3`
- Policy is evaluated before any execution call in enforce mode.
- Policy input includes tenant, scope, template, and risk-relevant metadata.
- Decision outcomes (`allow`, `deny`, `requires_approval`) are logged.

4. `TB-4`
- Sandbox runs non-root with constrained resources.
- Filesystem and path operations are confined to workspace.
- Network disabled by default; opt-in by template and policy.

5. `TB-5`
- Postgres and Redis are internal-only.
- Tenant and scope are mandatory for reads/writes.
- Audit events are append-oriented and immutable by workflow path.

## Consequences

### Positive

- Clear, auditable control points for security and compliance.
- Better incident response due to request-level traceability.
- Reduced blast radius when a component is compromised.

### Trade-offs

- More operational complexity (policy lifecycle, multi-component observability).
- Additional latency from policy checks and boundary validation.
- Strong dependence on consistent tenant/scope propagation.

## Security Invariants

- Untrusted code never executes outside sandbox boundary.
- Public traffic never reaches executor internal endpoints directly.
- Policy denial blocks execution in enforce mode.
- Cross-tenant access is denied by default.

## Operational Guardrails

- Changes to boundary contracts require ADR update.
- Boundary-affecting changes require security review.
- CI must validate policy syntax/evaluation and workflow import.

## Follow-ups

- ADR-002: tenancy and data isolation model details.
- Add boundary-aware threat model checklist to M1 issue #6.
