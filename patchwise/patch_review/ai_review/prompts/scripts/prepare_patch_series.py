#!/usr/bin/env python3
"""Build a deterministic Mode A/B patch-series manifest.

The review-commits orchestrator runs this after commits/patches are available
and before spawning reviewers.  It records the normalized per-patch facts that
were previously scattered across shell variables, sidecars, and prose prompts.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

DT_RE = re.compile(r"(^|/)(Documentation/devicetree/bindings/)|\.(dts|dtsi|yaml)$")
# Match real OF/DT API usage, not incidental "of_" substrings like number_of_,
# out_of_, or copy_of_ that appear in ordinary C diffs. of_match_table is kept
# explicit because it can appear as a struct field initializer without a call.
OF_API_RE = re.compile(
    r"\bof_match_table\b|"
    r"\bdevice_get_match_data\b|"
    r"\bof_(match_device|match_node|device_get_match_data|device_is_compatible|"
    r"find_compatible_node|find_node_by|get_property|property_read|property_present|"
    r"property_count|node_|parse_phandle|address_to_resource|iomap|irq_get|irq_parse|"
    r"alias_get|get_child|for_each_)\w*\b|"
    r"\bfor_each_\w*child_of_node\b"
)
SUBSYSTEM_PATH_PREFIXES = ("drivers/", "arch/", "firmware/", "soc/", "sound/", "net/", "block/", "crypto/")
HARDWARE_PATH_RE = re.compile(r"(^|/)(drivers|arch|sound|net|block|crypto|firmware|soc)/")
HARDWARE_TEXT_RE = re.compile(
    r"\b("
    r"readl|writel|ioremap|regmap_\w*|clk_\w*|reset_\w*|"
    r"gpiod_\w*|irq\w*|request_irq|dma_\w*|dmaengine_\w*|"
    r"pm_runtime\w*|pm_clk_\w*|dev_pm_\w*|devm_\w*|"
    r"probe|remove|hotplug|percpu|per_cpu|cpu_online|"
    r"pinctrl_pm_\w*|icc_\w*|geni_icc_\w*|"
    r"geni_se_resources_\w*|geni_se_clk_\w*|clk_round_rate|"
    r"get_\w*clk_cfg|set_rate|setup_\w*xfer|power[-_ ]?domain|"
    r"performance[-_ ]?state|opp"
    r")\b",
    re.IGNORECASE,
)
PATCH_SCOPE_RE = re.compile(r"\b(RFC|WIP|squash|fixup|partial|cleanup|refactor|split)\b", re.I)
COMMIT_MESSAGE_RE = re.compile(r"^(fixup!|squash!)|\b(Fixes:|Cc:\s*stable|Link:|Reviewed-by:|Acked-by:)\b", re.I | re.M)
BUILD_DESCRIPTOR_NAMES = {"Kconfig", "Kbuild", "Makefile"}


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


def parse_commits_file(path: Path) -> list[str]:
    commits = split_lines(path.read_text(encoding="utf-8"))
    if not commits:
        raise ValueError(f"no commits listed in {path}")
    return commits


def mode_b_commits(project: Path, total: int, review_tip: str) -> list[str]:
    text = run_git(project, ["rev-list", "--reverse", f"{review_tip}~{total}..{review_tip}"])
    commits = split_lines(text)
    if len(commits) != total:
        raise ValueError(f"expected {total} commits for Mode B, found {len(commits)}")
    return commits


def subject(project: Path, commit: str) -> str:
    return run_git(project, ["log", "--format=%s", "-1", commit])


def body(project: Path, commit: str) -> str:
    return run_git(project, ["log", "--format=%B", "-1", commit])


def files(project: Path, commit: str) -> list[str]:
    return split_lines(run_git(project, ["show", "--format=", "--name-only", commit]))


def patch_text(project: Path, commit: str) -> str:
    return run_git(project, ["show", "--format=", "--find-renames", commit])


def has_fixes(message: str) -> bool:
    return bool(re.search(r"(?m)^Fixes:\s+", message))


def touches_dt_file(paths: Iterable[str]) -> bool:
    """Patch changes an actual DT file: binding schema, .dts, .dtsi, or .yaml."""
    return any(DT_RE.search(path) for path in paths)


def changed_diff_text(diff_text: str) -> str:
    """Return only added/removed source lines, excluding diff metadata."""
    changed_lines: list[str] = []
    for line in diff_text.splitlines():
        if not line or line[0] not in {"+", "-"}:
            continue
        if line.startswith(("+++", "---")):
            continue
        changed_lines.append(line[1:])
    return "\n".join(changed_lines)


def uses_of_api(diff_text: str) -> bool:
    """Changed lines call the OF/DT driver API."""
    return bool(OF_API_RE.search(changed_diff_text(diff_text)))


def touches_dt(paths: Iterable[str], diff_text: str) -> bool:
    """Any DT surface — a DT file or OF driver API. Kept for callers/tests."""
    return touches_dt_file(paths) or uses_of_api(diff_text)


def touches_hardware(paths: Iterable[str], diff_text: str) -> bool:
    """Patch changes hardware-facing paths and hardware-facing code lines."""
    return any(HARDWARE_PATH_RE.search(path) for path in paths) and bool(
        HARDWARE_TEXT_RE.search(changed_diff_text(diff_text))
    )


def memory_categories(paths: list[str], message: str, diff_text: str, dt: bool, hardware: bool) -> list[str]:
    categories: list[str] = []
    if PATCH_SCOPE_RE.search(message) or len(paths) > 5:
        categories.append("patch-scope")
    if COMMIT_MESSAGE_RE.search(message):
        categories.append("commit-message")
    if dt:
        categories.append("dt-bindings")
    if hardware or any(path.startswith(SUBSYSTEM_PATH_PREFIXES) for path in paths):
        categories.append("subsystem-specific")
    return categories


def rule_args(patch: dict[str, object]) -> list[str]:
    args: list[str] = []
    # A DT-file change pulls the full schema/DTS checklist (dt-binding.md);
    # a driver-only of_* change pulls just the driver API rules (dt-driver.md).
    # Since the of_* rules (old 3d.3) now live only in dt-driver.md, a patch
    # that changes both a DT file and of_* code emits BOTH flags.
    if patch.get("dt_file"):
        args.append("--dt")
    if patch.get("dt_driver"):
        args.append("--dt-driver")
    if patch["hardware"]:
        args.append("--hardware")
    for category in patch["memory"]:
        args.extend(["--memory", str(category)])
    if patch["memory"]:
        for path in patch["files"]:
            args.extend(["--scope-file", str(path)])
    return args


def is_build_descriptor(path: str) -> bool:
    return Path(path).name in BUILD_DESCRIPTOR_NAMES


def descriptor_dir(path: str) -> str:
    return str(Path(path).parent)


def under_dir(path: str, directory: str) -> bool:
    if directory in {"", "."}:
        return True
    return path == directory or path.startswith(directory.rstrip("/") + "/")


def dependency_reasons(prior: dict[str, object], current: dict[str, object]) -> list[str]:
    prior_files = set(str(path) for path in prior["files"])
    current_files = set(str(path) for path in current["files"])
    reasons: list[str] = []

    shared = sorted(prior_files & current_files)
    if shared:
        reasons.append("shared files: " + ", ".join(shared[:4]))

    prior_descriptors = [path for path in prior_files if is_build_descriptor(path)]
    current_descriptors = [path for path in current_files if is_build_descriptor(path)]
    for descriptor in prior_descriptors:
        directory = descriptor_dir(descriptor)
        if any(under_dir(path, directory) for path in current_files):
            reasons.append(f"earlier build descriptor {descriptor} covers later files")
            break
    for descriptor in current_descriptors:
        directory = descriptor_dir(descriptor)
        if any(under_dir(path, directory) for path in prior_files):
            reasons.append(f"later build descriptor {descriptor} covers earlier files")
            break

    if prior["dt"] and current["dt"]:
        prior_dirs = {descriptor_dir(path) for path in prior_files if path.endswith((".dts", ".dtsi", ".yaml"))}
        current_dirs = {descriptor_dir(path) for path in current_files if path.endswith((".dts", ".dtsi", ".yaml"))}
        shared_dt_dirs = sorted(prior_dirs & current_dirs)
        if shared_dt_dirs:
            reasons.append("shared DT/binding directory: " + ", ".join(shared_dt_dirs[:3]))

    return reasons


def assign_dependency_groups(patches: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[int, list[int]] = {}
    for index, patch in enumerate(patches):
        dependencies: list[dict[str, object]] = []
        for prior in patches[:index]:
            reasons = dependency_reasons(prior, patch)
            if reasons:
                dependencies.append({"n": prior["n"], "reasons": reasons})
        patch["dependencies"] = dependencies
        patch["group"] = 1 + max((patches[int(dep["n"]) - 1]["group"] for dep in dependencies), default=0)
        groups.setdefault(int(patch["group"]), []).append(int(patch["n"]))

    return [{"group": group, "patches": patches_in_group} for group, patches_in_group in sorted(groups.items())]


def build_manifest(
    project: Path,
    mode: str,
    slug: str,
    commits: list[str],
    review_base: str,
    review_tip: str,
    output: Path,
) -> dict[str, object]:
    patches: list[dict[str, object]] = []
    for index, commit in enumerate(commits, start=1):
        commit_subject = subject(project, commit)
        commit_body = body(project, commit)
        changed_files = files(project, commit)
        diff_text = patch_text(project, commit)
        dt_file = touches_dt_file(changed_files)
        dt_driver = uses_of_api(diff_text)
        dt = dt_file or dt_driver
        hardware = touches_hardware(changed_files, diff_text)
        patch = {
            "n": index,
            "total": len(commits),
            "hash": commit,
            "short_hash": commit[:12],
            "subject": commit_subject,
            "files": changed_files,
            "fixes": has_fixes(commit_body),
            "dt": dt,
            "dt_file": dt_file,
            "dt_driver": dt_driver,
            "hardware": hardware,
            "memory": memory_categories(changed_files, commit_body, diff_text, dt, hardware),
            "paths": {
                "diff": f"tmp/patch_{index}_diff.txt",
                "build": f"tmp/patch_{index}_build.txt",
                "rules": f"tmp/patch_{index}_rules.md",
                "block": f"tmp/patch_{index}_block.html",
            },
        }
        patch["rule_args"] = rule_args(patch)
        patches.append(patch)

    groups = assign_dependency_groups(patches)

    return {
        "schema": "review-commits.patch-series-manifest.v1",
        "mode": mode,
        "slug": slug,
        "review_base": review_base,
        "review_tip": review_tip,
        "total": len(commits),
        "output": str(output),
        "groups": groups,
        "patches": patches,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a review-commits Mode A/B patch-series manifest")
    parser.add_argument("--project", required=True, type=Path, help="Kernel project path")
    parser.add_argument("--mode", required=True, choices=("A", "B"), help="Review mode")
    parser.add_argument("--slug", required=True, help="Review slug")
    parser.add_argument("--output", required=True, type=Path, help="Manifest JSON output path")
    parser.add_argument("--review-base", required=True, help="Base commit or <root>")
    parser.add_argument("--review-tip", required=True, help="Review tip commit")
    parser.add_argument("--commits-file", type=Path, help="Mode A ordered commits file")
    parser.add_argument("--total", type=int, help="Mode B patch count")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    project = args.project.expanduser().resolve()
    output = args.output.expanduser()

    try:
        if args.mode == "A":
            if not args.commits_file:
                raise ValueError("Mode A requires --commits-file")
            commits = parse_commits_file(args.commits_file.expanduser())
        else:
            if not args.total:
                raise ValueError("Mode B requires --total")
            commits = mode_b_commits(project, args.total, args.review_tip)

        manifest = build_manifest(
            project=project,
            mode=args.mode,
            slug=args.slug,
            commits=commits,
            review_base=args.review_base,
            review_tip=args.review_tip,
            output=output,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"prepare_patch_series.py: {exc}", file=sys.stderr)
        return 1

    print(f"wrote patch-series manifest: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
