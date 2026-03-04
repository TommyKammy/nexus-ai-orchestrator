#!/usr/bin/env bash
set -euo pipefail

docker run --rm -v "$PWD:/work" -w /work python:3.11-slim bash -lc "\
  pip install --no-cache-dir -r executor/requirements.txt && \
  pytest -q executor/test_sandbox.py"
