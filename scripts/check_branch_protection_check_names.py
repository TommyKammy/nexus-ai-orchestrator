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
    REPO_ROOT / "docs" / "branch-protection-checks-runbook.md",
    REPO_ROOT / "docs" / "release-process.md",
]
JOB_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


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


def _leading_spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _strip_inline_comment(line: str) -> str:
    in_single_quote = False
    in_double_quote = False
    stripped: list[str] = []

    for idx, char in enumerate(line):
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        elif char == "#" and not in_single_quote and not in_double_quote:
            previous = line[idx - 1] if idx > 0 else ""
            if idx == 0 or previous.isspace():
                break
        stripped.append(char)

    return "".join(stripped).rstrip()


def _parse_mapping_entry(line: str) -> tuple[str, str] | None:
    if ":" not in line:
        return None

    key, value = line.split(":", 1)
    key = key.strip()
    if not key:
        return None

    return key, value.strip()


def _normalize_scalar(value: str) -> str:
    normalized = value.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
        return normalized[1:-1].strip()
    return normalized


def parse_workflow_jobs(workflow_path: Path) -> list[tuple[str, str]]:
    lines = workflow_path.read_text(encoding="utf-8").splitlines()
    jobs_indent: int | None = None
    job_indent: int | None = None
    current_property_indent: int | None = None
    current_job_id: str | None = None
    current_job_name: str | None = None
    parsed_jobs: list[tuple[str, str]] = []

    for raw_line in lines:
        line = _strip_inline_comment(raw_line)
        if not line.strip():
            continue

        indent = _leading_spaces(line)
        content = line[indent:]

        if jobs_indent is None:
            if indent == 0 and content == "jobs:":
                jobs_indent = indent
            continue

        if indent <= jobs_indent:
            if current_job_id is not None:
                parsed_jobs.append((current_job_id, current_job_name or current_job_id))
            break

        if content.endswith(":"):
            candidate_job_id = content[:-1].strip()
            if JOB_KEY_RE.fullmatch(candidate_job_id) and (job_indent is None or indent == job_indent):
                if current_job_id is not None:
                    parsed_jobs.append((current_job_id, current_job_name or current_job_id))
                current_job_id = candidate_job_id
                current_job_name = None
                current_property_indent = None
                job_indent = indent
                continue

        if current_job_id is None or job_indent is None or indent <= job_indent:
            continue

        if content.startswith("-"):
            continue

        if current_property_indent is None:
            current_property_indent = indent

        if indent != current_property_indent:
            continue

        parsed_entry = _parse_mapping_entry(content)
        if parsed_entry is None:
            continue

        key, value = parsed_entry
        if key == "name" and current_job_name is None:
            current_job_name = _normalize_scalar(value)

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
    aliases: set[str] = set()
    for check_name in required_checks:
        for producer in produced_checks.get(check_name, []):
            producer_path = producer.rsplit(":", 1)[0]
            workflow_path = Path(producer_path)
            workflow_name = read_workflow_name(workflow_path)
            if workflow_name:
                aliases.add(f"{workflow_name} / {check_name}")
    return sorted(aliases)


def read_workflow_name(workflow_path: Path) -> str | None:
    for raw_line in workflow_path.read_text(encoding="utf-8").splitlines():
        line = _strip_inline_comment(raw_line)
        if not line.strip():
            continue

        if _leading_spaces(line) != 0:
            continue

        parsed_entry = _parse_mapping_entry(line)
        if parsed_entry is None:
            continue

        key, value = parsed_entry
        if key == "name":
            return _normalize_scalar(value)
    return None


def _legacy_doc_alias_pattern(required_checks: list[str]) -> re.Pattern[str]:
    check_names = sorted((re.escape(check_name) for check_name in required_checks), key=len, reverse=True)
    alternation = "|".join(check_names)
    return re.compile(
        rf"(?:^|[\s([{{'\"`])(?P<alias>[^`\n/][^`\n/]*? / (?P<check>{alternation}))"
        rf"(?=$|[\s)\]}}.,;:!?'\"`])"
    )


def validate_docs(doc_paths: list[Path], required_checks: list[str]) -> list[str]:
    errors: list[str] = []
    legacy_alias_pattern = _legacy_doc_alias_pattern(required_checks)

    for doc_path in doc_paths:
        content = doc_path.read_text(encoding="utf-8")
        legacy_aliases = {match.group("alias") for match in legacy_alias_pattern.finditer(content)}
        for alias in sorted(legacy_aliases):
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

    for doc_path in doc_paths:
        if not doc_path.exists():
            errors.append(f"{doc_path}: doc file not found")

    existing_docs = [doc_path for doc_path in doc_paths if doc_path.exists()]
    errors.extend(validate_docs(existing_docs, required_checks))
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
