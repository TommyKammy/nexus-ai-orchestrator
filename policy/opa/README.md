# OPA Policies

This directory contains OPA policy modules for centralized execution control.

## Decision API

The executor and workflows call:

`POST /v1/data/ai/policy/result`

Canonical contract reference:

- `docs/policy-input-output-contract.md`

With input shape:

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

- `POLICY_MODE=shadow`: evaluate and log only
- `POLICY_MODE=enforce`: block `deny` and `requires_approval`
- `POLICY_FAIL_MODE=open|closed`: behavior on OPA outage
