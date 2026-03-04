#!/usr/bin/env python3
"""Validate baseline n8n workflow JSON schema for repository workflows.

This intentionally enforces a minimal structural contract so malformed JSON or
structurally invalid workflow exports fail CI quickly.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
from pathlib import Path
from typing import Any


def _err(filepath: Path, message: str) -> str:
    return f"{filepath}: {message}"


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def validate_workflow(filepath: Path) -> list[str]:
    errors: list[str] = []

    try:
        raw = filepath.read_text(encoding="utf-8")
    except OSError as exc:
        return [_err(filepath, f"read error: {exc}")]

    try:
        workflow = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [_err(filepath, f"invalid JSON: {exc.msg} at line {exc.lineno} col {exc.colno}")]

    if not isinstance(workflow, dict):
        return [_err(filepath, "top-level JSON must be an object")]

    if not _is_non_empty_str(workflow.get("name")):
        errors.append(_err(filepath, "missing/invalid top-level 'name'"))

    nodes = workflow.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errors.append(_err(filepath, "'nodes' must be a non-empty array"))
        return errors

    node_names: list[str] = []

    for idx, node in enumerate(nodes):
        label = f"node[{idx}]"
        if not isinstance(node, dict):
            errors.append(_err(filepath, f"{label} must be an object"))
            continue

        name = node.get("name")
        if not _is_non_empty_str(name):
            errors.append(_err(filepath, f"{label} missing/invalid 'name'"))
        else:
            node_names.append(name)

        if not _is_non_empty_str(node.get("type")):
            errors.append(_err(filepath, f"{label} missing/invalid 'type'"))

        if not isinstance(node.get("parameters"), dict):
            errors.append(_err(filepath, f"{label} missing/invalid 'parameters' object"))

        position = node.get("position")
        if position is not None:
            if (
                not isinstance(position, list)
                or len(position) != 2
                or not all(isinstance(v, (int, float)) for v in position)
            ):
                errors.append(_err(filepath, f"{label} 'position' must be a [x, y] numeric array"))

        if node.get("type") == "n8n-nodes-base.webhook":
            params = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}
            if not _is_non_empty_str(params.get("path")):
                errors.append(_err(filepath, f"{label} webhook node missing/invalid parameters.path"))
            if not _is_non_empty_str(params.get("httpMethod")):
                errors.append(_err(filepath, f"{label} webhook node missing/invalid parameters.httpMethod"))

    # Node names must be unique so connections are deterministic.
    name_counts = Counter(node_names)
    duplicates = {name for name, count in name_counts.items() if count > 1}
    if duplicates:
        errors.append(_err(filepath, f"duplicate node name(s): {', '.join(sorted(duplicates))}"))

    connections = workflow.get("connections")
    if not isinstance(connections, dict):
        errors.append(_err(filepath, "missing/invalid top-level 'connections' object"))
        return errors

    valid_names = set(node_names)

    for source_name, source_mapping in connections.items():
        if source_name not in valid_names:
            errors.append(_err(filepath, f"connections source '{source_name}' does not match any node name"))
            continue

        if not isinstance(source_mapping, dict):
            errors.append(_err(filepath, f"connections['{source_name}'] must be an object"))
            continue

        # n8n exports usually use "main": [[{...}], [...]]
        main_routes = source_mapping.get("main")
        if main_routes is None:
            continue
        if not isinstance(main_routes, list):
            errors.append(_err(filepath, f"connections['{source_name}'].main must be an array"))
            continue

        for branch_idx, branch in enumerate(main_routes):
            if not isinstance(branch, list):
                errors.append(
                    _err(filepath, f"connections['{source_name}'].main[{branch_idx}] must be an array")
                )
                continue

            for link_idx, link in enumerate(branch):
                if not isinstance(link, dict):
                    errors.append(
                        _err(
                            filepath,
                            f"connections['{source_name}'].main[{branch_idx}][{link_idx}] must be an object",
                        )
                    )
                    continue

                target_name = link.get("node")
                if not _is_non_empty_str(target_name):
                    errors.append(
                        _err(
                            filepath,
                            f"connections['{source_name}'].main[{branch_idx}][{link_idx}] missing/invalid 'node'",
                        )
                    )
                elif target_name not in valid_names:
                    errors.append(
                        _err(
                            filepath,
                            f"connections link from '{source_name}' points to unknown node '{target_name}'",
                        )
                    )

                if not _is_non_empty_str(link.get("type")):
                    errors.append(
                        _err(
                            filepath,
                            f"connections['{source_name}'].main[{branch_idx}][{link_idx}] missing/invalid 'type'",
                        )
                    )

                index = link.get("index")
                if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                    errors.append(
                        _err(
                            filepath,
                            f"connections['{source_name}'].main[{branch_idx}][{link_idx}] missing/invalid non-negative 'index'",
                        )
                    )

    return errors


def validate_directory(directory: Path) -> list[str]:
    errors: list[str] = []
    if not directory.exists() or not directory.is_dir():
        return [f"{directory}: directory does not exist"]

    files = sorted(directory.glob("*.json"))
    if not files:
        return [f"{directory}: no JSON workflow files found"]

    for filepath in files:
        errors.extend(validate_workflow(filepath))

    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate baseline n8n workflow JSON schema")
    parser.add_argument(
        "directories",
        nargs="*",
        default=["n8n/workflows", "n8n/workflows-v3"],
        help="Directories containing workflow JSON files",
    )
    args = parser.parse_args(argv)

    all_errors: list[str] = []
    for directory in args.directories:
        all_errors.extend(validate_directory(Path(directory)))

    if all_errors:
        print("Workflow schema validation FAILED")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    print("Workflow schema validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
