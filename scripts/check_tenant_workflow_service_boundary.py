#!/usr/bin/env python3
"""Fail when tenant-facing n8n workflows still embed direct Postgres access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

TARGET_WORKFLOWS = (
    "n8n/workflows-v3/01_memory_ingest.json",
    "n8n/workflows-v3/02_vector_search.json",
    "n8n/workflows-v3/03_audit_append.json",
    "n8n/workflows-v3/04_executor_dispatch.json",
    "n8n/workflows-v3/05_policy_approval.json",
    "n8n/workflows-v3/06_policy_registry_upsert.json",
    "n8n/workflows-v3/07_policy_registry_publish.json",
    "n8n/workflows-v3/08_policy_registry_list.json",
    "n8n/workflows-v3/09_policy_registry_get.json",
    "n8n/workflows-v3/10_policy_registry_candidates.json",
    "n8n/workflows-v3/11_policy_candidate_seed.json",
    "n8n/workflows-v3/12_policy_registry_delete.json",
)


def _error(workflow_path: Path, message: str) -> str:
    return f"{workflow_path}: {message}"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_workflow_has_no_postgres_nodes(workflow_path: Path) -> list[str]:
    try:
        workflow = _load_json(workflow_path)
    except FileNotFoundError:
        return [_error(workflow_path, "workflow file not found")]
    except OSError as exc:
        return [_error(workflow_path, f"read error: {exc}")]
    except json.JSONDecodeError as exc:
        return [_error(workflow_path, f"invalid JSON: {exc.msg} at line {exc.lineno} col {exc.colno}")]

    if not isinstance(workflow, dict):
        return [_error(workflow_path, "top-level JSON must be an object")]

    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        return [_error(workflow_path, "missing/invalid 'nodes' array")]

    errors: list[str] = []
    for idx, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(_error(workflow_path, f"node[{idx}] must be an object"))
            continue

        if node.get("type") != "n8n-nodes-base.postgres":
            continue

        node_name = node.get("name") if isinstance(node.get("name"), str) else f"node[{idx}]"
        errors.append(
            _error(
                workflow_path,
                f"tenant-facing workflow must not use postgres node '{node_name}'; move data access behind a dedicated service boundary",
            )
        )

    return errors


def validate_repo(root: Path, workflows: tuple[str, ...] = TARGET_WORKFLOWS) -> list[str]:
    errors: list[str] = []
    for relative_path in workflows:
        errors.extend(validate_workflow_has_no_postgres_nodes(root / relative_path))
    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Validate that tenant-facing workflows orchestrate service calls instead of direct Postgres access"
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root containing the target n8n workflows",
    )
    args = parser.parse_args(argv)

    errors = validate_repo(Path(args.repo_root))
    if errors:
        print("Tenant workflow service-boundary check FAILED")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("Tenant workflow service-boundary check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
