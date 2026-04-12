#!/usr/bin/env bash
set -euo pipefail

docker run --rm -v "$PWD:/work" -w /work python:3.11-slim bash -lc "\
  pip install --no-cache-dir -r executor/requirements.txt && \
  pytest -q \
    executor/test_sandbox.py \
    executor/test_api_server_execute.py \
    executor/test_api_server_session_lifecycle.py \
    executor/test_policy_client.py \
    executor/test_templates.py \
    tests/test_postgres_tenant_rls.py"
