package ai.policy

import rego.v1

test_risk_score_zero_for_low_risk_request if {
	score := data.ai.policy.risk_score with input as {
		"subject": {"tenant_id": "t1", "scope": "analysis", "role": "api"},
		"resource": {"tenant_id": "t1", "scope": "analysis", "task_type": "code_execution"},
		"action": "executor.execute",
		"context": {"network_enabled": false, "payload_size": 32},
	}
	score == 0
}

test_risk_score_component_accumulation if {
	score := data.ai.policy.risk_score with input as {
		"subject": {"tenant_id": "t1", "scope": "analysis", "role": "api"},
		"resource": {"tenant_id": "t1", "scope": "admin:ops", "task_type": "unknown_task"},
		"action": "executor.execute",
		"context": {"network_enabled": true, "payload_size": 200000},
	}
	score == 105
}

test_requires_approval_when_risk_reaches_threshold if {
	threshold := data.policy.thresholds.requires_approval
	result := data.ai.policy.result with input as {
		"subject": {
			"tenant_id": "t1",
			"scope": "analysis",
			"role": "api",
			"network_admin": true
		},
		"resource": {"tenant_id": "t1", "scope": "analysis", "task_type": "code_execution"},
		"action": "executor.execute",
		"context": {"network_enabled": true, "payload_size": 10}
	}
	result.risk_score == threshold
	result.decision == "requires_approval"
	result.requires_approval
	not result.allow
	result.reasons == ["high_risk_requires_approval"]
}
