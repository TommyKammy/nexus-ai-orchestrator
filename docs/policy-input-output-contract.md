# OPA Policy Input/Output Contract

This document defines the canonical policy decision contract used by the executor and workflows.

## Endpoint

- Method: `POST`
- Path: `/v1/data/ai/policy/result`
- Body envelope:

```json
{
  "input": {
    "subject": {},
    "resource": {},
    "action": "executor.execute",
    "context": {}
  }
}
```

## Input Contract

Required top-level fields under `input`:

- `subject` (object): caller identity and tenancy context
  - `tenant_id` (string)
  - `scope` (string)
  - `role` (string)
- `resource` (object): target execution/session context
- `action` (string): policy action key (`executor.execute`, `executor.session.create`, `executor.session.execute`, etc.)
- `context` (object): runtime context (for example `payload_size`, `network_enabled`, `request_id`, `ttl`)

Example input:

```json
{
  "input": {
    "subject": {
      "tenant_id": "t1",
      "scope": "analysis",
      "role": "api"
    },
    "resource": {
      "tenant_id": "t1",
      "scope": "analysis",
      "template": "default",
      "language": "python",
      "task_type": "code_execution"
    },
    "action": "executor.execute",
    "context": {
      "request_id": "req-123",
      "payload_size": 120,
      "network_enabled": false
    }
  }
}
```

## Output Contract

Policy result object fields (`result` from OPA):

- `policy_id` (string)
- `policy_version` (string)
- `decision` (string enum): `allow`, `deny`, `requires_approval`
- `allow` (boolean)
- `requires_approval` (boolean)
- `risk_score` (integer)
- `reasons` (string array)

### Example: Allow

```json
{
  "result": {
    "policy_id": "executor-core-v1",
    "policy_version": "2026-02-20",
    "decision": "allow",
    "allow": true,
    "requires_approval": false,
    "risk_score": 0,
    "reasons": []
  }
}
```

### Example: Requires Approval

```json
{
  "result": {
    "policy_id": "executor-core-v1",
    "policy_version": "2026-02-20",
    "decision": "requires_approval",
    "allow": false,
    "requires_approval": true,
    "risk_score": 55,
    "reasons": ["high_risk_requires_approval"]
  }
}
```

### Example: Deny

```json
{
  "result": {
    "policy_id": "executor-core-v1",
    "policy_version": "2026-02-20",
    "decision": "deny",
    "allow": false,
    "requires_approval": false,
    "risk_score": 90,
    "reasons": ["task_type_not_allowed"]
  }
}
```

## Raw OPA Response vs PolicyClient Result

The examples above show the raw OPA HTTP shape (`{"result": ...}`).

`executor/policy_client.py` returns a normalized object (no outer `result` key) and always includes `error`:

```json
{
  "policy_id": "executor-core-v1",
  "policy_version": "2026-02-20",
  "decision": "allow",
  "allow": true,
  "requires_approval": false,
  "risk_score": 0,
  "reasons": [],
  "error": null
}
```

Callers of `PolicyClient.evaluate()` should consume this normalized shape.

## Failure/Fallback Semantics

Default executor posture is `POLICY_MODE=enforce` with `POLICY_FAIL_MODE=closed`.

Unsafe advisory or fail-open operation is blocked at startup unless an operator explicitly sets `POLICY_ALLOW_UNSAFE=true` for development-only override scenarios.

When OPA is unavailable, `executor/policy_client.py` returns fallback results in the same normalized shape above (no outer `result` key), based on `POLICY_FAIL_MODE`:

- `open`: `decision=allow`, `allow=true`, `requires_approval=false`
- `closed`: `decision=deny`, `allow=false`, `requires_approval=true`

These fallback responses still include `policy_id=fallback`, `policy_version=fallback`, `reasons=["policy_unavailable"]`, and a non-null `error` value.
