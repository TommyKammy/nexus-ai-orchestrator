# Issue #126: Replace privileged DinD with a non-privileged execution runtime

## Supervisor Snapshot
- Issue URL: https://github.com/TommyKammy/nexus-ai-orchestrator/issues/126
- Branch: codex/issue-126
- Workspace: .
- Journal: .codex-supervisor/issues/126/issue-journal.md
- Current phase: reproducing
- Attempt count: 1 (implementation=1, repair=0)
- Last head SHA: 9dfa3f84edf9a8f32b87c59af01a483a4da7dfbb
- Blocked reason: none
- Last failure signature: none
- Repeated failure signature count: 0
- Updated at: 2026-04-13T11:32:27.086Z

## Latest Codex Summary
- Added a focused regression asserting `docker-compose.executor.yml` does not use `privileged: true` and requires an explicit non-privileged runtime.
- Switched the executor compose path from privileged DinD posture to `runtime: sysbox-runc`, tightened `security_opt` to `no-new-privileges:true`, and renamed the service container to `ai-executor-runtime`.
- Updated deployment/operator docs and the production deploy script to require Sysbox and to stop referring to the old `ai-executor-dind` container name.
- Focused verification passed with `python3 -m unittest tests.test_k8s_security_posture`.
- Broader Docker-backed verification is currently blocked in this shell because Docker cannot reach a daemon and `docker compose` is not available as a plugin here.

## Active Failure Context
- None recorded.

## Codex Working Notes
### Current Handoff
- Hypothesis: The narrowest reproducible failure is the executor compose manifest still declaring `privileged: true`; replacing that with an explicit Sysbox runtime should satisfy the issue’s core security posture change without touching the sandbox API yet.
- What changed: Added a manifest security regression in `tests/test_k8s_security_posture.py`; updated `docker-compose.executor.yml` to use `runtime: sysbox-runc` and `no-new-privileges:true`; updated `scripts/deploy-executor-production.sh`, `executor/README.md`, and `SECURITY.md` for the Sysbox-based deployment path.
- Current blocker: Local Docker-backed verification is blocked by environment tooling. `docker compose --env-file .env.example -f docker-compose.executor.yml config -q` fails here because this Docker installation does not expose `compose`, and `bash scripts/ci/lint.sh` fails because no Docker daemon is reachable.
- Next exact step: Run the requested compose validation and CI scripts in an environment with Docker daemon access plus Docker Compose plugin support, then fix any runtime-specific follow-up if Sysbox config handling differs on a real host.
- Verification gap: Have not exercised `docker compose ... config -q` successfully in this shell and have not run `bash scripts/ci/test.sh` because Docker is unavailable.
- Files touched: docker-compose.executor.yml; tests/test_k8s_security_posture.py; scripts/deploy-executor-production.sh; executor/README.md; SECURITY.md
- Rollback concern: Hosts without Sysbox configured will now fail deployment fast in the production script until `sysbox-runc` is installed and registered with Docker.
- Last focused command: python3 -m unittest tests.test_k8s_security_posture
### Scratchpad
- Reproducer failure before fix: `AssertionError` on `privileged: true` in `tests.test_k8s_security_posture`.
- Host-tooling failures after fix:
  - `docker compose --env-file .env.example -f docker-compose.executor.yml config -q` -> `unknown flag: --env-file`
  - `bash scripts/ci/lint.sh` -> `Cannot connect to the Docker daemon`
