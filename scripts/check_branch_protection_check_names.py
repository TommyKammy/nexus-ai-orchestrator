#!/usr/bin/env python3
"""Validate canonical branch protection required check names.

The canonical required checks live in a repo-local manifest so workflow and
operator-doc drift is detected before GitHub branch protection blocks merges.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "scripts" / "ci" / "branch_protection_required_checks.json"
DEFAULT_WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
DEFAULT_DOCS = [
    REPO_ROOT / "docs" / "production-readiness-checklist.md",
    REPO_ROOT / "docs" / "release-process.md",
]
JOB_KEY_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
JOB_NAME_RE = re.compile(r"^    name:\s*(.+?)\s*$")


def load_required_checks(manifest_path: Path, branch: str) -> list[str]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks = data.get(branch)
    if not isinstance(checks, list) or not checks:
        raise ValueError(f"{manifest_path}: missing non-empty list for branch '{branch}'")

    normalized: list[str] = []
    for idx, check_name in enumerate(checks):
        if not isinstance(check_name, str) or not check_name.strip():
            raise ValueError(f"{manifest_path}: invalid check entry at index {idx}")
        normalized.append(check_name.strip())

    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{manifest_path}: duplicate check names for branch '{branch}'")

    return normalized


def parse_workflow_jobs(workflow_path: Path) -> list[tuple[str, str]]:
    lines = workflow_path.read_text(encoding="utf-8").splitlines()
    jobs_started = False
    current_job_id: str | None = None
    current_job_name: str | None = None
    parsed_jobs: list[tuple[str, str]] = []

    for line in lines:
        if not jobs_started:
            if line == "jobs:":
                jobs_started = True
            continue

        if line and not line.startswith(" "):
            break

        job_key_match = JOB_KEY_RE.match(line)
        if job_key_match:
            if current_job_id is not None:
                parsed_jobs.append((current_job_id, current_job_name or current_job_id))
            current_job_id = job_key_match.group(1)
            current_job_name = None
            continue

        if current_job_id is None:
            continue

        job_name_match = JOB_NAME_RE.match(line)
        if job_name_match and current_job_name is None:
            current_job_name = job_name_match.group(1).strip().strip("\"'")

    if current_job_id is not None:
        parsed_jobs.append((current_job_id, current_job_name or current_job_id))

    return parsed_jobs


def collect_workflow_checks(workflow_dir: Path) -> tuple[dict[str, list[str]], list[str]]:
    workflow_paths = sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml"))
    if not workflow_paths:
        return {}, [f"{workflow_dir}: no workflow files found"]

    produced_checks: dict[str, list[str]] = {}
    errors: list[str] = []

    for workflow_path in workflow_paths:
        jobs = parse_workflow_jobs(workflow_path)
        if not jobs:
            errors.append(f"{workflow_path}: no jobs found")
            continue

        for job_id, check_name in jobs:
            produced_checks.setdefault(check_name, []).append(f"{workflow_path}:{job_id}")

    for check_name, producers in sorted(produced_checks.items()):
        if len(producers) > 1:
            joined = ", ".join(producers)
            errors.append(f"duplicate produced check name '{check_name}' from {joined}")

    return produced_checks, errors


def legacy_doc_aliases_for_required_checks(
    required_checks: list[str], produced_checks: dict[str, list[str]]
) -> list[str]:
    aliases: list[str] = []
    for check_name in required_checks:
        producers = produced_checks.get(check_name, [])
        if not producers:
            continue

        producer_path = producers[0].split(":", 1)[0]
        workflow_path = Path(producer_path)
        workflow_name = read_workflow_name(workflow_path)
        if workflow_name:
            aliases.append(f"{workflow_name} / {check_name}")
    return aliases


def read_workflow_name(workflow_path: Path) -> str | None:
    for line in workflow_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return None


def validate_docs(doc_paths: list[Path], legacy_aliases: list[str]) -> list[str]:
    errors: list[str] = []

    for doc_path in doc_paths:
        content = doc_path.read_text(encoding="utf-8")
        for alias in legacy_aliases:
            if alias in content:
                errors.append(
                    f"{doc_path}: replace legacy workflow/job display name '{alias}' "
                    "with the exact reported check name"
                )

    return errors


def validate_branch_protection_check_names(
    manifest_path: Path,
    workflow_dir: Path,
    branch: str,
    doc_paths: list[Path],
) -> list[str]:
    errors: list[str] = []

    try:
        required_checks = load_required_checks(manifest_path, branch)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [str(exc)]

    produced_checks, workflow_errors = collect_workflow_checks(workflow_dir)
    errors.extend(workflow_errors)

    for check_name in required_checks:
        if check_name not in produced_checks:
            errors.append(
                f"required check '{check_name}' for branch '{branch}' is not produced by any workflow job"
            )

    legacy_aliases = legacy_doc_aliases_for_required_checks(required_checks, produced_checks)
    for doc_path in doc_paths:
        if not doc_path.exists():
            errors.append(f"{doc_path}: doc file not found")

    existing_docs = [doc_path for doc_path in doc_paths if doc_path.exists()]
    errors.extend(validate_docs(existing_docs, legacy_aliases))
    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate canonical branch protection required checks")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--workflow-dir", type=Path, default=DEFAULT_WORKFLOW_DIR)
    parser.add_argument("--branch", default="main")
    parser.add_argument("docs", nargs="*", type=Path, default=DEFAULT_DOCS)
    args = parser.parse_args(argv)

    errors = validate_branch_protection_check_names(
        manifest_path=args.manifest,
        workflow_dir=args.workflow_dir,
        branch=args.branch,
        doc_paths=args.docs,
    )
    if errors:
        print("Branch protection check name validation FAILED")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(f"Branch protection check name validation passed for '{args.branch}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
