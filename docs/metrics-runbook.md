# Executor Metrics Runbook

## Purpose
This document defines the executor metrics exposed at:
- `/metrics` (JSON for service diagnostics)
- `/metrics/prometheus` (Prometheus exposition format)

## Metric Groups

### Policy metrics
Source: `metrics.policy` and `executor_policy_*`

- `executor_policy_eval_total`
  - Meaning: total policy evaluations
  - Alert draft: sudden drop to zero during traffic may indicate policy path breakage
- `executor_policy_decisions_total{decision=...}`
  - Meaning: decision distribution (`allow`, `deny`, `requires_approval`)
  - Alert draft: spike in `deny`/`requires_approval` ratio compared with baseline
- `executor_policy_eval_errors_total`
  - Meaning: policy client/evaluation errors
  - Alert draft: `rate(...) > 0` for 5m
- `executor_policy_eval_latency_ms_avg`
  - Meaning: average policy evaluation latency
  - Alert draft: sustained `> 200ms` for 10m

### Request metrics
Source: `metrics.requests` and `executor_http_*`

- `executor_http_requests_total`
  - Meaning: total executor HTTP requests handled
- `executor_http_request_errors_total`
  - Meaning: responses with status `>= 400`
  - Alert draft: error ratio > 5% for 10m
- `executor_http_request_latency_ms_avg`
  - Meaning: average end-to-end executor request latency
  - Alert draft: sustained `> 500ms` for 10m
- `executor_http_requests_by_method_total{method=...}`
  - Meaning: request volume split by HTTP method
- `executor_http_requests_by_status_total{status=...}`
  - Meaning: request volume split by response status code

### Session metrics
Source: `metrics.*` from session manager

Representative fields include current active sessions and lifecycle counters from `SessionManager`.
Alert draft:
- active sessions near configured max for sustained period
- failed/destroyed session anomalies

## Scrape Alignment
Prometheus scrape configuration is defined in:
- `k8s/config/deployment/prometheus-monitoring.yaml`

Executor scrape path is configured to `/metrics/prometheus`.

## Basic Verification
```bash
curl -s http://localhost:8080/metrics | jq .
curl -s http://localhost:8080/metrics/prometheus
```

Expected:
- both endpoints return `200`
- policy, session, and request metric groups are present
