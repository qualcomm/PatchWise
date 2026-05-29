#!/usr/bin/env python3
"""Validate a review-commits Mode A/B patch-series manifest.

The manifest is the orchestrator's source of truth for patch identity, rule
selection, artifact paths, and dependency groups.  Keep this validator strict:
an invalid manifest should stop review preparation before subagents receive
incorrect patch metadata.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCHEMA = "review-commits.patch-series-manifest.v1"
MODES = {"A", "B"}
MEMORY_CATEGORIES = {
    "patch-scope",
    "commit-message",
    "dt-bindings",
    "subsystem-specific",
}
PATH_KEYS = {
    "diff": "tmp/patch_{n}_diff.txt",
    "build": "tmp/patch_{n}_build.txt",
    "rules": "tmp/patch_{n}_rules.md",
    "block": "tmp/patch_{n}_block.html",
}


def run_git(project: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(project),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.rstrip("\n")


def split_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line]


def expected_rule_args(patch: dict[str, Any]) -> list[str]:
    args: list[str] = []
    # Mirror scripts/prepare_patch_series.py rule_args(): a DT-file change emits
    # --dt (full schema/DTS checklist); a driver-only of_* change emits
    # --dt-driver (driver API rules); a patch that does both emits both.
    if patch.get("dt_file") is True:
        args.append("--dt")
    if patch.get("dt_driver") is True:
        args.append("--dt-driver")
    if patch.get("hardware") is True:
        args.append("--hardware")
    for category in patch.get("memory", []):
        args.extend(["--memory", str(category)])
    if patch.get("memory"):
        for path in patch.get("files", []):
            args.extend(["--scope-file", str(path)])
    return args


def validate_path(path: str) -> str | None:
    if not path:
        return "empty path"
    if path.startswith("/"):
        return "absolute path is not allowed"
    parts = Path(path).parts
    if ".." in parts:
        return "parent-directory component is not allowed"
    return None


def validate_manifest(manifest: Any, args: argparse.Namespace) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest root must be a JSON object"]

    schema = manifest.get("schema")
    if schema != SCHEMA:
        errors.append(f"schema must be {SCHEMA!r}, got {schema!r}")

    mode = manifest.get("mode")
    if mode not in MODES:
        errors.append(f"mode must be one of {sorted(MODES)}, got {mode!r}")
    if args.mode and mode != args.mode:
        errors.append(f"mode mismatch: expected {args.mode!r}, got {mode!r}")

    slug = manifest.get("slug")
    if not isinstance(slug, str) or not slug:
        errors.append("slug must be a non-empty string")
    if args.slug and slug != args.slug:
        errors.append(f"slug mismatch: expected {args.slug!r}, got {slug!r}")

    review_base = manifest.get("review_base")
    review_tip = manifest.get("review_tip")
    if not isinstance(review_base, str) or not review_base:
        errors.append("review_base must be a non-empty string")
    if not isinstance(review_tip, str) or not review_tip:
        errors.append("review_tip must be a non-empty string")
    if args.review_base and review_base != args.review_base:
        errors.append(f"review_base mismatch: expected {args.review_base!r}, got {review_base!r}")
    if args.review_tip and review_tip != args.review_tip:
        errors.append(f"review_tip mismatch: expected {args.review_tip!r}, got {review_tip!r}")

    total = manifest.get("total")
    if not isinstance(total, int) or total <= 0:
        errors.append(f"total must be a positive integer, got {total!r}")
        total = 0
    if args.total is not None and total != args.total:
        errors.append(f"total mismatch: expected {args.total}, got {total}")

    output = manifest.get("output")
    if not isinstance(output, str) or not output:
        errors.append("output must be a non-empty string")

    patches = manifest.get("patches")
    if not isinstance(patches, list):
        errors.append("patches must be a list")
        patches = []
    if total and len(patches) != total:
        errors.append(f"patch count mismatch: total={total}, patches={len(patches)}")

    seen_numbers: set[int] = set()
    group_by_patch: dict[int, int] = {}
    for index, patch in enumerate(patches, start=1):
        if not isinstance(patch, dict):
            errors.append(f"patch {index}: must be an object")
            continue

        n = patch.get("n")
        if n != index:
            errors.append(f"patch {index}: n must be {index}, got {n!r}")
        if isinstance(n, int):
            if n in seen_numbers:
                errors.append(f"patch {index}: duplicate n={n}")
            seen_numbers.add(n)

        if patch.get("total") != total:
            errors.append(f"patch {index}: total must be {total}, got {patch.get('total')!r}")

        commit = patch.get("hash")
        if not isinstance(commit, str) or not commit:
            errors.append(f"patch {index}: hash must be a non-empty string")
        short_hash = patch.get("short_hash")
        if not isinstance(short_hash, str) or not isinstance(commit, str) or short_hash != commit[:12]:
            errors.append(f"patch {index}: short_hash must match hash[:12]")

        subject = patch.get("subject")
        if not isinstance(subject, str) or not subject.strip():
            errors.append(f"patch {index}: subject must be non-empty")

        files = patch.get("files")
        if not isinstance(files, list) or not all(isinstance(path, str) for path in files):
            errors.append(f"patch {index}: files must be a list of strings")
            files = []
        if not files:
            errors.append(f"patch {index}: files must not be empty")
        if len(files) != len(set(files)):
            errors.append(f"patch {index}: files must not contain duplicates")
        for path in files:
            path_error = validate_path(path)
            if path_error:
                errors.append(f"patch {index}: invalid file path {path!r}: {path_error}")

        for key in ("fixes", "dt", "dt_file", "dt_driver", "hardware"):
            if not isinstance(patch.get(key), bool):
                errors.append(f"patch {index}: {key} must be boolean")

        memory = patch.get("memory")
        if not isinstance(memory, list) or not all(isinstance(category, str) for category in memory):
            errors.append(f"patch {index}: memory must be a list of strings")
            memory = []
        unknown_memory = sorted(set(memory) - MEMORY_CATEGORIES)
        if unknown_memory:
            errors.append(f"patch {index}: unknown memory categories: {', '.join(unknown_memory)}")
        if len(memory) != len(set(memory)):
            errors.append(f"patch {index}: memory categories must not contain duplicates")
        if patch.get("dt") is True and "dt-bindings" not in memory:
            errors.append(f"patch {index}: dt patch must include dt-bindings memory")
        if patch.get("hardware") is True and "subsystem-specific" not in memory:
            errors.append(f"patch {index}: hardware patch must include subsystem-specific memory")
        # dt is the union flag retained for the dependency graph; it must agree
        # with the split dt_file/dt_driver flags that drive rule_args.
        if isinstance(patch.get("dt"), bool) and isinstance(patch.get("dt_file"), bool) \
                and isinstance(patch.get("dt_driver"), bool):
            if patch["dt"] != (patch["dt_file"] or patch["dt_driver"]):
                errors.append(
                    f"patch {index}: dt must equal dt_file or dt_driver "
                    f"(dt={patch['dt']}, dt_file={patch['dt_file']}, dt_driver={patch['dt_driver']})"
                )

        expected_args = expected_rule_args(patch)
        if patch.get("rule_args") != expected_args:
            errors.append(
                f"patch {index}: rule_args mismatch: expected {expected_args!r}, got {patch.get('rule_args')!r}"
            )

        paths = patch.get("paths")
        if not isinstance(paths, dict):
            errors.append(f"patch {index}: paths must be an object")
            paths = {}
        for key, template in PATH_KEYS.items():
            expected_path = template.format(n=index)
            if paths.get(key) != expected_path:
                errors.append(f"patch {index}: paths.{key} must be {expected_path!r}, got {paths.get(key)!r}")

        dependencies = patch.get("dependencies")
        if not isinstance(dependencies, list):
            errors.append(f"patch {index}: dependencies must be a list")
            dependencies = []
        for dep in dependencies:
            if not isinstance(dep, dict):
                errors.append(f"patch {index}: dependency entries must be objects")
                continue
            dep_n = dep.get("n")
            if not isinstance(dep_n, int) or dep_n < 1 or dep_n >= index:
                errors.append(f"patch {index}: dependency n must refer to an earlier patch, got {dep_n!r}")
            reasons = dep.get("reasons")
            if not isinstance(reasons, list) or not reasons or not all(isinstance(reason, str) and reason for reason in reasons):
                errors.append(f"patch {index}: dependency reasons must be non-empty strings")

        group = patch.get("group")
        if not isinstance(group, int) or group <= 0:
            errors.append(f"patch {index}: group must be a positive integer")
        else:
            group_by_patch[index] = group

    expected_numbers = set(range(1, total + 1)) if total else set()
    if total and seen_numbers != expected_numbers:
        errors.append(f"patch numbers must be exactly 1..{total}, got {sorted(seen_numbers)}")

    validate_groups(manifest.get("groups"), total, group_by_patch, errors)
    if args.project:
        validate_against_git(args.project.expanduser().resolve(), patches, review_base, review_tip, errors)
    return errors


def validate_groups(groups: Any, total: int, group_by_patch: dict[int, int], errors: list[str]) -> None:
    if not isinstance(groups, list):
        errors.append("groups must be a list")
        return

    covered: list[int] = []
    previous_group = 0
    for index, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            errors.append(f"groups[{index}]: must be an object")
            continue
        group_id = group.get("group")
        patches = group.get("patches")
        if not isinstance(group_id, int) or group_id <= 0:
            errors.append(f"groups[{index}]: group must be a positive integer")
            continue
        if group_id <= previous_group:
            errors.append(f"groups[{index}]: groups must be sorted and unique")
        previous_group = group_id
        if not isinstance(patches, list) or not patches or not all(isinstance(n, int) for n in patches):
            errors.append(f"groups[{index}]: patches must be a non-empty list of integers")
            continue
        if patches != sorted(patches):
            errors.append(f"groups[{index}]: patches must be sorted")
        for patch_n in patches:
            covered.append(patch_n)
            if patch_n < 1 or patch_n > total:
                errors.append(f"groups[{index}]: patch {patch_n} outside 1..{total}")
            if group_by_patch.get(patch_n) != group_id:
                errors.append(
                    f"groups[{index}]: patch {patch_n} group mismatch: "
                    f"patch has {group_by_patch.get(patch_n)!r}, group entry has {group_id!r}"
                )

    expected = list(range(1, total + 1)) if total else []
    if sorted(covered) != expected:
        errors.append(f"groups must cover each patch exactly once: expected {expected}, got {sorted(covered)}")
    if len(covered) != len(set(covered)):
        errors.append("groups must not list a patch more than once")


def validate_against_git(
    project: Path,
    patches: list[Any],
    review_base: Any,
    review_tip: Any,
    errors: list[str],
) -> None:
    if not project.is_dir():
        errors.append(f"project path does not exist: {project}")
        return
    try:
        run_git(project, ["rev-parse", "--is-inside-work-tree"])
    except subprocess.CalledProcessError as exc:
        errors.append(f"project is not a git work tree: {exc.stderr.strip() or exc}")
        return

    if isinstance(review_tip, str) and review_tip:
        try:
            run_git(project, ["cat-file", "-e", f"{review_tip}^{{commit}}"])
        except subprocess.CalledProcessError:
            errors.append(f"review_tip is not a commit: {review_tip}")
    if isinstance(review_base, str) and review_base and review_base != "<root>":
        try:
            run_git(project, ["cat-file", "-e", f"{review_base}^{{commit}}"])
        except subprocess.CalledProcessError:
            errors.append(f"review_base is not a commit: {review_base}")

    for index, patch in enumerate(patches, start=1):
        if not isinstance(patch, dict) or not isinstance(patch.get("hash"), str):
            continue
        commit = patch["hash"]
        try:
            run_git(project, ["cat-file", "-e", f"{commit}^{{commit}}"])
            git_subject = run_git(project, ["log", "--format=%s", "-1", commit])
            git_files = split_lines(run_git(project, ["show", "--format=", "--name-only", commit]))
        except subprocess.CalledProcessError as exc:
            errors.append(f"patch {index}: git validation failed for {commit}: {exc.stderr.strip() or exc}")
            continue
        if patch.get("subject") != git_subject:
            errors.append(f"patch {index}: subject differs from git commit subject")
        if patch.get("files") != git_files:
            errors.append(f"patch {index}: files differ from git changed-file list")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a review-commits patch-series manifest")
    parser.add_argument("manifest", type=Path, help="Manifest JSON path")
    parser.add_argument("--project", type=Path, help="Optional git project path for commit cross-checks")
    parser.add_argument("--mode", choices=sorted(MODES), help="Expected review mode")
    parser.add_argument("--slug", help="Expected review slug")
    parser.add_argument("--review-base", help="Expected review base")
    parser.add_argument("--review-tip", help="Expected review tip")
    parser.add_argument("--total", type=int, help="Expected patch count")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"validate_series_manifest.py: cannot read {args.manifest}: {exc}", file=sys.stderr)
        return 1

    errors = validate_manifest(manifest, args)
    if errors:
        print(f"series manifest invalid: {args.manifest}", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"series manifest valid: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
