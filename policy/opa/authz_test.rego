package ai.policy

import rego.v1

test_authz_allow_executor_execute if {
	result := data.ai.policy.result with input as {
		"subject": {"tenant_id": "t1", "scope": "analysis", "role": "api"},
		"resource": {"tenant_id": "t1", "scope": "analysis", "task_type": "code_execution"},
		"action": "executor.execute",
		"context": {"network_enabled": false},
	} with data.ai.policy.risk_score as 0
	result.decision == "allow"
	result.allow
	not result.requires_approval
	result.risk_score == 0
	result.reasons == []
}

test_authz_deny_disallowed_task_type if {
	result := data.ai.policy.result with input as {
		"subject": {"tenant_id": "t1", "scope": "analysis", "role": "api"},
		"resource": {"tenant_id": "t1", "scope": "analysis", "task_type": "delete_everything"},
		"action": "executor.execute",
		"context": {"network_enabled": false},
	} with data.ai.policy.risk_score as 0
	result.decision == "deny"
	not result.allow
	result.risk_score == 0
	result.reasons == ["task_type_not_allowed"]
}

test_authz_deny_scope_mismatch if {
	result := data.ai.policy.result with input as {
		"subject": {"tenant_id": "t1", "scope": "analysis", "role": "api"},
		"resource": {"tenant_id": "t1", "scope": "admin", "task_type": "code_execution"},
		"action": "executor.execute",
		"context": {"network_enabled": false},
	} with data.ai.policy.risk_score as 0
	result.decision == "deny"
	not result.allow
	result.risk_score == 0
	result.reasons == ["scope_mismatch"]
}

test_authz_deny_missing_tenancy if {
	result := data.ai.policy.result with input as {
		"subject": {"tenant_id": "t1", "scope": "analysis", "role": "api"},
		"resource": {"tenant_id": "t1", "task_type": "code_execution"},
		"action": "executor.execute",
		"context": {"network_enabled": false},
	} with data.ai.policy.risk_score as 0
	result.decision == "deny"
	not result.allow
	result.risk_score == 0
	result.reasons == ["missing_tenancy"]
}

test_authz_deny_tenant_mismatch if {
	result := data.ai.policy.result with input as {
		"subject": {"tenant_id": "t1", "scope": "analysis", "role": "api"},
		"resource": {"tenant_id": "t2", "scope": "analysis", "task_type": "code_execution"},
		"action": "executor.execute",
		"context": {"network_enabled": false},
	} with data.ai.policy.risk_score as 0
	result.decision == "deny"
	not result.allow
	result.risk_score == 0
	result.reasons == ["tenant_mismatch"]
}

test_authz_deny_network_not_allowed if {
	result := data.ai.policy.result with input as {
		"subject": {"tenant_id": "t1", "scope": "analysis", "role": "api"},
		"resource": {"tenant_id": "t1", "scope": "analysis", "task_type": "code_execution"},
		"action": "executor.execute",
		"context": {"network_enabled": true},
	} with data.ai.policy.risk_score as 0
	result.decision == "deny"
	not result.allow
	result.risk_score == 0
	result.reasons == ["network_not_allowed"]
}

test_authz_requires_approval_high_risk if {
	result := data.ai.policy.result with input as {
		"subject": {"tenant_id": "t1", "scope": "analysis", "role": "api"},
		"resource": {"tenant_id": "t1", "scope": "analysis", "task_type": "code_execution"},
		"action": "executor.execute",
		"context": {"network_enabled": false},
	} with data.ai.policy.risk_score as 55
	result.decision == "requires_approval"
	not result.allow
	result.requires_approval
	result.risk_score == 55
	result.reasons == ["high_risk_requires_approval"]
}
