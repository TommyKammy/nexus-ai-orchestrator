# OPA Policies

This directory contains OPA policy modules for centralized execution control.

## Decision API

The executor and workflows call:

`POST /v1/data/ai/policy/result`

Canonical contract reference:

- [docs/policy-input-output-contract.md](../../docs/policy-input-output-contract.md)

Inner policy input object shape (this is the value under OPA HTTP `input`):

```json
{
  "subject": {
    "tenant_id": "t1",
    "scope": "user:123",
    "role": "workflow"
  },
  "resource": {
    "scope": "user:123",
    "task_type": "ping"
  },
  "action": "executor.execute",
  "context": {
    "network_enabled": false,
    "payload_size": 120
  }
}
```

## Result shape

Inner policy result object shape (this is the value under OPA HTTP `result`):
```json
{
  "policy_id": "executor-core-v1",
  "policy_version": "2026-02-20",
  "decision": "allow",
  "allow": true,
  "requires_approval": false,
  "risk_score": 0,
  "reasons": []
}
```

## Modes

- Default posture: `POLICY_MODE=enforce` and `POLICY_FAIL_MODE=closed`
- `POLICY_MODE=shadow`: evaluate and log only. Requires `POLICY_ALLOW_UNSAFE=true`.
- `POLICY_MODE=enforce`: block `deny` and `requires_approval`
- `POLICY_FAIL_MODE=closed`: deny requests if OPA is unavailable
- `POLICY_FAIL_MODE=open`: allow requests if OPA is unavailable. Requires `POLICY_ALLOW_UNSAFE=true`.

## Local policy tests

```bash
opa test policy/opa/ -d policy/opa/data.json
```
