#!/usr/bin/env bash
set -euo pipefail

python3 scripts/validate_workflow_schema.py n8n/workflows n8n/workflows-v3
