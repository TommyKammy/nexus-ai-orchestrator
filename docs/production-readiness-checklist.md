# Production Readiness Checklist

Date: 2026-03-05
Owner: Platform/Operations

## 1) Technical Gates

- [ ] CI required checks green (`quality-gates`, `validate/import-test`, `policy-and-executor`, `security-audit`)
- [ ] Core compose journey passes (`pnpm e2e`)
- [ ] Kubernetes smoke validation completed (`scripts/ci/k8s_smoke_test.sh`)
- [ ] Release workflow available for SemVer tags (`.github/workflows/release.yml`)
- [ ] Rollback and DR runbook published (`docs/rollback-dr-runbook.md`)

## 2) Operational Gates

- [ ] On-call escalation path confirmed
- [ ] Backup/restore procedure validated for n8n/postgres (`scripts/n8n-upgrade-backup.sh`, `scripts/n8n-rollback.sh`)
- [ ] DR drill evidence recorded (`docs/reports/dr-drill-20260305.md`)
- [ ] Release cut and rollback procedure documented (`docs/release-process.md`)

## 3) Security Gates

- [ ] Security audit report refreshed (`docs/reports/security-audit-report-20260305.md`)
- [ ] CI security scans integrated (`.github/workflows/security-audit.yml`)
- [ ] Critical/High findings at zero in baseline scan
- [ ] Secret scanning enabled in CI

## 4) Dependency Completion Gates

- [ ] #41 Security closeout is closed
- [ ] #42 Rollback/DR runbook is closed
- [ ] #43 Release automation is closed

## 5) Approval Record

- Change window:
- Release candidate:
- Final decision (`Go` / `No-Go`):
- Decision timestamp (UTC):
- Incident commander / approver:
- Notes:
