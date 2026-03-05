#!/usr/bin/env bash
set -euo pipefail

bash scripts/ci/security_dependency_scan.sh
bash scripts/ci/security_secret_scan.sh
bash scripts/ci/security_misconfig_baseline_check.sh
