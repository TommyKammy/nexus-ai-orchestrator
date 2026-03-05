# SLO / Alert Runbook

## Objective
Define operational SLO targets, alert criteria, and first-response actions for on-call engineers.

## SLI / SLO Definitions

### Availability
- SLI: successful executor API responses ratio
  - Formula: `1 - (5xx responses / total requests)`
- SLO target:
  - 99.9% monthly availability for executor API

### Latency
- SLI: request latency from `executor_http_request_latency_ms_avg`
- SLO targets:
  - p50 proxy target: < 300ms
  - p95 proxy target: < 800ms
  - sustained average threshold: < 500ms over 10m

### Error rate
- SLI: `executor_http_request_errors_total / executor_http_requests_total`
- SLO target:
  - error ratio < 5% over rolling 10m windows

## Alert Conditions

### Critical
- Executor API unavailable:
  - condition: no healthy executor scrape target for > 2m
- OPA policy engine down:
  - condition: `sum(up{namespace="executor-system",pod=~"opa-.*"}) == 0` for > 2m

### Warning
- High queue depth:
  - condition: queue depth metric > 50 for > 2m
- High CPU utilization:
  - condition: pool CPU utilization > 90% for > 5m
- Session migration failures:
  - condition: `rate(executor_session_migration_failures_total[5m]) > 0`
- Elevated executor error ratio:
  - condition: HTTP error ratio > 5% for > 10m
- Elevated executor latency:
  - condition: request latency average > 500ms for > 10m

## Mapping to Monitoring Config
Source file: `k8s/config/deployment/prometheus-monitoring.yaml`

| Runbook area | Config section |
| --- | --- |
| Executor pool up/down | `PrometheusRule.rules.alert: ExecutorPoolDown` |
| Queue depth | `ExecutorHighQueueDepth` |
| CPU utilization | `ExecutorHighCPUUtilization` |
| Session migration failures | `ExecutorSessionMigrationFailed` |
| OPA availability | `OpaPolicyEngineDown` |
| Scrape paths | `ServiceMonitor` entries (`executor-pools`, `executor-load-balancer`, `opa-policy`) |

## On-call First Response

### 1. Triage and scope
1. Confirm active alert in Alertmanager/Prometheus.
2. Identify impacted component (executor pool, load balancer, OPA).
3. Check blast radius (single tenant, single pool, all traffic).

### 2. Quick diagnostics
1. Verify executor metrics endpoints:
   - `curl -s http://localhost:8080/metrics | jq .`
   - `curl -s http://localhost:8080/metrics/prometheus`
2. Check recent request/error trends:
   - `executor_http_requests_total`
   - `executor_http_request_errors_total`
   - `executor_http_request_latency_ms_avg`
3. Check policy path health:
   - `executor_policy_eval_errors_total`
   - OPA pod status/scrape health

### 3. Immediate mitigations
1. If pool pressure is high, scale executor pools up.
2. If OPA is unavailable, fail mode decision:
   - maintain current fail-open/fail-closed policy mode as documented for the environment.
3. If error rate spikes due deploy regression, roll back the latest release.

## Escalation
1. `sev-1` conditions (availability major impact) -> page platform owner immediately.
2. `sev-2` sustained latency/error breaches -> notify platform + workflow owners.
3. If unresolved after 30 minutes, escalate to incident commander.

## Recovery Criteria
System is considered recovered when all are true:
1. Critical alerts cleared for at least 15 minutes.
2. Error ratio remains below 5% for 15 minutes.
3. Latency average remains below 500ms for 15 minutes.
4. OPA scrape targets healthy and policy eval error rate stable.

## Post-incident follow-up
1. Record timeline and root cause.
2. Update thresholds/runbook if tuning is needed.
3. Add regression tests or alert rule improvements for recurrence prevention.
