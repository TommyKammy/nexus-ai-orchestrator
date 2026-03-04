# Security Threat Model v1

- Status: Active
- Date: 2026-03-04
- Related issue: #6
- Related ADRs:
  - `docs/adr/adr-001-architecture-and-trust-boundaries.md`
  - `docs/adr/adr-002-tenancy-and-data-isolation-model.md`

## Scope

This threat model covers:

- Caddy edge and ingress
- n8n workflow orchestration
- OPA policy decision path
- Executor API and sandbox execution
- PostgreSQL and Redis data boundaries

It does not cover:

- cloud account/IAM posture outside this repository
- host OS hardening beyond documented deployment practices

## Security Objectives

1. Prevent unauthorized code execution.
2. Prevent cross-tenant data access.
3. Preserve integrity and traceability of audit events.
4. Minimize blast radius from compromised components.

## Assets

- API credentials and webhook keys
- tenant execution metadata (`tenant_id`, `scope`)
- policy definitions and revisions
- audit logs and decision metadata
- session and cache state

## Threat Actors

- external unauthenticated attacker
- authenticated but unauthorized tenant user
- compromised workflow or internal service
- operator misconfiguration (non-malicious)

## Trust Boundaries

- `TB-1` Internet -> Caddy
- `TB-2` Caddy -> n8n
- `TB-3` n8n/Executor -> OPA
- `TB-4` Executor API -> sandbox containers
- `TB-5` service layer -> PostgreSQL/Redis

## Threat Scenarios and Controls

| ID | Threat | Boundary | Impact | Existing controls | Residual risk |
|---|---|---|---|---|---|
| T1 | Unauthenticated webhook abuse | TB-1/TB-2 | Unauthorized task triggering | API key validation, rate limiting, security headers | Key leakage risk remains |
| T2 | Policy bypass for execution | TB-3/TB-4 | Unapproved code execution | OPA evaluation and enforce mode | Misconfigured `POLICY_FAIL_MODE=open` |
| T3 | Cross-tenant scope abuse | TB-3/TB-5 | Data leakage | `tenant_id` + `scope` propagation, scope mismatch deny rule | Missing-key deny rules require strict tests |
| T4 | Sandbox escape / privilege escalation | TB-4 | Host compromise | Non-root sandbox, no-new-privileges, capability drop, resource limits | Privileged DinD still raises residual risk |
| T5 | Path traversal/file abuse | TB-4 | File overwrite/read outside workspace | Secure path validation and confinement | New file handlers may regress |
| T6 | Audit tampering | TB-5 | Forensic integrity loss | Append-only trigger + hash chain migration (`20260220_audit_hardening.sql`) | DB superuser compromise |
| T7 | Policy registry mispublish | TB-3/TB-5 | Unsafe rule activation | revision/publish logs, explicit status model | Human approval workflow depends on ops discipline |
| T8 | Resource exhaustion (DoS) | TB-1/TB-4 | Service degradation | quotas, TTL sessions, rate limits | sustained distributed traffic |

## Security Checklist v1

### PR and CI Checklist

- [ ] Threat-relevant changes identify affected trust boundaries (`TB-1..TB-5`)
- [ ] Policy changes include `opa check` and `opa eval` evidence
- [ ] Workflow changes pass schema/import validation
- [ ] No secrets committed (`.env.example` remains sanitized)
- [ ] Risks and rollback steps are documented in PR description

### Deployment Checklist

- [ ] `POLICY_MODE=enforce` in production
- [ ] `POLICY_FAIL_MODE=closed` in production (unless temporary exception approved)
- [ ] API/webhook auth enabled and rotated
- [ ] Caddy rate limits and security headers active
- [ ] Network policies + resource quotas applied (K8s) or equivalent compose controls
- [ ] Container images scanned before release
- [ ] Audit log append-only triggers present in DB
- [ ] Monitoring/alerting configured for auth failures, policy denies, and execution errors

### Operational Checklist

- [ ] Periodic review of wildcard policy entries (`tenant_id='*'`, `scope_pattern='*'`)
- [ ] Incident drill includes audit-chain verification and rollback path
- [ ] Dependency/image updates reviewed for security impact
- [ ] Threat model reviewed at least once per quarter or after architecture changes

## Open Risks and Follow-ups

1. Replace privileged DinD with a stronger runtime path (Sysbox or rootless approach).
2. Enforce deny-on-missing tenancy keys for all execution actions in policy tests.
3. Expand e2e abuse-case tests (cross-tenant, malformed payloads, excessive input).
