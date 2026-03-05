# K8s Smoke/Load Suite Report (2026-03-05)

## Scope
- Issue: #39
- Scripts:
  - `scripts/ci/k8s_smoke_test.sh`
  - `scripts/ci/k8s_load_test.sh`

## Verification Commands

```bash
bash scripts/ci/k8s_smoke_test.sh
bash scripts/ci/k8s_load_test.sh
```

## Smoke Result
- status: `passed`
- health endpoint: `GET /health -> 200`
- basic API call: `GET /stats -> 200`
- report file: `artifacts/k8s-tests/k8s-smoke-report-20260305-134354.md`

## Load Result
- status: `passed`
- target endpoint: `/health`
- total requests: `120`
- throughput: `18.32 req/s`
- p95 latency: `12.756 ms`
- error rate: `0.00 %`
- report file: `artifacts/k8s-tests/k8s-load-report-20260305-134403.md`

## Notes
- Runtime artifacts are generated under `artifacts/k8s-tests/`.
- CI workflow `k8s-smoke-load.yml` uploads these artifacts for manual runs.
