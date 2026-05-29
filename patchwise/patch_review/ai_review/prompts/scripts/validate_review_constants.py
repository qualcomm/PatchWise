#!/usr/bin/env python3
"""Validate review-commits shared constants and mirrored prose references."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def load_constants(skill_dir: Path) -> dict:
    path = skill_dir / "refs" / "review-constants.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - CLI should print the exact load error.
        raise SystemExit(f"ERROR: could not load {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"ERROR: {path} must contain a JSON object")
    return data


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def require_text(path: Path, needle: str, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    require(needle in text, f"{path}: missing {needle!r}", errors)


def validate_schema(constants: dict, errors: list[str]) -> None:
    require(constants.get("schema") == "review-commits.constants.v1", "schema must be review-commits.constants.v1", errors)

    source_audit = constants.get("source_audit")
    require(isinstance(source_audit, dict), "source_audit must be an object", errors)
    if isinstance(source_audit, dict):
        for key in ("pre_passed_context_files", "on_demand_read_budget_per_patch", "targeted_read_max_lines"):
            value = source_audit.get(key)
            require(isinstance(value, int) and value > 0, f"source_audit.{key} must be a positive integer", errors)
        require(bool(source_audit.get("large_file_strategy")), "source_audit.large_file_strategy must be non-empty", errors)

    html_report = constants.get("html_report")
    require(isinstance(html_report, dict), "html_report must be an object", errors)
    if isinstance(html_report, dict):
        for key in (
            "required_classes",
            "standard_verdicts",
            "standard_severities",
            "forbidden_labels",
            "forbidden_classes",
        ):
            value = html_report.get(key)
            require(isinstance(value, list) and all(isinstance(item, str) and item for item in value), f"html_report.{key} must be a non-empty string list", errors)
        require(bool(html_report.get("required_cannot_apply_finding_class")), "html_report.required_cannot_apply_finding_class must be non-empty", errors)
        require(bool(html_report.get("qgenie_footer_text")), "html_report.qgenie_footer_text must be non-empty", errors)

    runtime_overrides = constants.get("runtime_overrides")
    require(isinstance(runtime_overrides, dict), "runtime_overrides must be an object", errors)
    if isinstance(runtime_overrides, dict):
        for key in ("sparse_disabled_marker", "sparse_disabled_summary_note"):
            require(bool(runtime_overrides.get(key)), f"runtime_overrides.{key} must be non-empty", errors)


def _load_server_default_constants(skill_dir: Path) -> tuple[dict | None, str | None]:
    """Return server fallback constants when this skill lives inside the repo."""
    repo_root = skill_dir.parents[1] if len(skill_dir.parents) > 1 else skill_dir.parent
    runner_path = repo_root / "server" / "patch_review" / "review_runner.py"
    if not runner_path.exists():
        return None, None

    server_dir = repo_root / "server"
    old_path = list(sys.path)
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location("_review_constants_runner", runner_path)
        if spec is None or spec.loader is None:
            return None, f"could not import {runner_path}"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - report exact import failure in CLI output.
        return None, f"could not import {runner_path}: {exc}"
    finally:
        sys.path[:] = old_path

    defaults = getattr(module, "_DEFAULT_REVIEW_CONSTANTS", None)
    if not isinstance(defaults, dict):
        return None, f"{runner_path}: _DEFAULT_REVIEW_CONSTANTS is missing or not a dict"
    return defaults, None


def _format_constant_path(path: tuple[str, ...]) -> str:
    return ".".join(path)


def _compare_constants(expected: object, actual: object, path: tuple[str, ...], errors: list[str]) -> None:
    if isinstance(expected, dict) and isinstance(actual, dict):
        expected_keys = set(expected)
        actual_keys = set(actual)
        for key in sorted(expected_keys - actual_keys):
            errors.append(f"server defaults missing {_format_constant_path((*path, key))}")
        for key in sorted(actual_keys - expected_keys):
            errors.append(f"server defaults contain extra {_format_constant_path((*path, key))}")
        for key in sorted(expected_keys & actual_keys):
            _compare_constants(expected[key], actual[key], (*path, key), errors)
        return
    if expected != actual:
        errors.append(
            f"server default drift at {_format_constant_path(path)}: "
            f"json={expected!r} server={actual!r}"
        )


def validate_server_defaults(skill_dir: Path, constants: dict, errors: list[str]) -> None:
    defaults, load_error = _load_server_default_constants(skill_dir)
    if load_error:
        errors.append(load_error)
        return
    if defaults is None:
        return
    _compare_constants(constants, defaults, ("review-constants",), errors)


def validate_mirrors(skill_dir: Path, constants: dict, errors: list[str]) -> None:
    audit = constants["source_audit"]
    context_files = audit["pre_passed_context_files"]
    read_budget = audit["on_demand_read_budget_per_patch"]
    max_lines = audit["targeted_read_max_lines"]
    html = constants["html_report"]

    startup_workflow = skill_dir / "refs" / "startup-workflow.md"
    workflow = skill_dir / "refs" / "orchestrator-workflow.md"

    require_text(startup_workflow, f"up to **{read_budget} targeted reads per patch**", errors)
    require_text(startup_workflow, f"the {context_files}\n  pre-passed context files", errors)
    require_text(startup_workflow, f"exceeds {max_lines} lines", errors)

    html_template = skill_dir / "refs" / "html-template.md"
    # Hard-lock the qgenie footer text in BOTH the template owner
    # (html-template.md) and the final-save workflow (orchestrator-workflow.md).
    # The two must not drift: html-template.md defines the footer markup and
    # orchestrator-workflow.md Step 6.5 emits it. If either copy is edited away
    # from review-constants.json, this mirror check fails.
    require_text(html_template, html["qgenie_footer_text"], errors)
    require_text(workflow, html["qgenie_footer_text"], errors)
    for verdict in html["standard_verdicts"]:
        if verdict == "CANNOT APPLY":
            require_text(startup_workflow, verdict, errors)
        else:
            require_text(html_template, verdict, errors)
    for severity in html["standard_severities"]:
        require_text(html_template, severity, errors)
    for class_name in html["required_classes"]:
        require_text(html_template, class_name, errors)
    require_text(html_template, html["required_cannot_apply_finding_class"], errors)

    # Runtime-override sentinel: keep the single source of truth (this JSON) in
    # lockstep with the workflow refs that instruct the model to write it.  If
    # someone rewords the sentinel in either place, this mirror check fails.
    overrides = constants["runtime_overrides"]
    marker = overrides["sparse_disabled_marker"]
    note = overrides["sparse_disabled_summary_note"]
    mode_c_workflow = skill_dir / "refs" / "mode-c-workflow.md"
    require_text(startup_workflow, marker, errors)
    require_text(startup_workflow, note, errors)
    require_text(mode_c_workflow, marker, errors)
    require_text(mode_c_workflow, note, errors)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skill-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Path to skills/review-commits (default: inferred from this script)",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    skill_dir = args.skill_dir.resolve()
    constants = load_constants(skill_dir)
    errors: list[str] = []
    validate_schema(constants, errors)
    if not errors:
        validate_mirrors(skill_dir, constants, errors)
        validate_server_defaults(skill_dir, constants, errors)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"review constants valid: {skill_dir / 'refs' / 'review-constants.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
