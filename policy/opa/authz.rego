package ai.policy

import rego.v1

default allow := false
default requires_approval := false

policy_id := "executor-core-v1"
policy_version := "2026-02-20"

decision := "allow" if allow
decision := "requires_approval" if requires_approval
decision := "deny" if {
	not allow
	not requires_approval
}

allow if {
	not deny_missing_tenancy
	not deny_tenant_mismatch
	not deny_task_type
	not deny_scope_mismatch
	not deny_network
	not approval_high_risk
}

requires_approval if approval_high_risk

deny_reasons contains "missing_tenancy" if deny_missing_tenancy
deny_reasons contains "tenant_mismatch" if deny_tenant_mismatch
deny_reasons contains "task_type_not_allowed" if deny_task_type
deny_reasons contains "scope_mismatch" if deny_scope_mismatch
deny_reasons contains "network_not_allowed" if deny_network
deny_reasons contains "high_risk_requires_approval" if approval_high_risk

protected_action if input.action == "executor.execute"
protected_action if input.action == "executor.session.create"
protected_action if input.action == "executor.session.execute"

tenancy_string(container, field) := value if {
	raw := object.get(container, field, "")
	is_string(raw)
	value := trim(raw, " \t\r\n")
}

tenancy_string(container, field) := "" if {
	raw := object.get(container, field, "")
	not is_string(raw)
}

missing_tenancy_field(container, field) if {
	tenancy_string(container, field) == ""
}

deny_missing_tenancy if {
	protected_action
	some field in ["tenant_id", "scope"]
	missing_tenancy_field(input.subject, field)
}

deny_missing_tenancy if {
	protected_action
	some field in ["tenant_id", "scope"]
	missing_tenancy_field(input.resource, field)
}

deny_tenant_mismatch if {
	protected_action
	subject_tenant_id := tenancy_string(input.subject, "tenant_id")
	resource_tenant_id := tenancy_string(input.resource, "tenant_id")
	subject_tenant_id != ""
	resource_tenant_id != ""
	subject_tenant_id != resource_tenant_id
}

deny_task_type if {
	input.action == "executor.execute"
	task_type := object.get(input.resource, "task_type", "")
	task_type == ""
}

deny_task_type if {
	input.action == "executor.execute"
	task_type := object.get(input.resource, "task_type", "")
	task_type != ""
	not task_type_allowed(task_type)
}

deny_scope_mismatch if {
	subject_scope := object.get(input.subject, "scope", "")
	resource_scope := object.get(input.resource, "scope", "")
	subject_scope != ""
	resource_scope != ""
	subject_scope != resource_scope
}

deny_network if {
	input.action == "executor.execute"
	object.get(input.context, "network_enabled", false)
	not object.get(input.subject, "network_admin", false)
}

approval_high_risk if {
	risk := data.ai.policy.risk_score
	risk >= data.policy.thresholds.requires_approval
	risk < data.policy.thresholds.deny
}

task_type_allowed(task_type) if task_type in data.policy.allowed_task_types

reasons := sort([r | r := deny_reasons[_]])

result := {
	"policy_id": policy_id,
	"policy_version": policy_version,
	"decision": decision,
	"allow": allow,
	"requires_approval": requires_approval,
	"risk_score": data.ai.policy.risk_score,
	"reasons": reasons,
}
