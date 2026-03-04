#!/usr/bin/env bash
set -euo pipefail

python3 -m py_compile \
  executor/api_server.py \
  executor/policy_client.py \
  executor/run_task.py \
  executor/sandbox.py \
  executor/session.py \
  executor/filesystem.py
