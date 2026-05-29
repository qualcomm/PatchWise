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

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from select_rule_cards import select_rule_cards
from _packet_patterns import (
    DT_RE,
    DT_BINDING_HEADER_RE,
    OF_API_RE,
    HARDWARE_PATH_RE,
    changed_diff_text,
)

HARDWARE_TEXT_RE = re.compile(
    r"\b("
    r"readl|writel|ioremap|regmap_\w*|clk_\w*|reset_\w*|"
    r"gpiod_\w*|irq\w*|request_irq|dma_\w*|dmaengine_\w*|"
    r"pm_runtime\w*|pm_clk_\w*|dev_pm_\w*|devm_\w*|"
    r"runtime_(?:suspend|resume)|system_(?:suspend|resume)|"
    r"probe|remove|hotplug|percpu|per_cpu|cpu_online|"
    r"pinctrl_pm_\w*|icc_\w*|geni_icc_\w*|"
    r"geni_se_resources_\w*|geni_se_clk_\w*|clk_round_rate|"
    r"get_\w*clk_cfg|set_rate|setup_\w*xfer|power[-_ ]?domain|"
    r"performance[-_ ]?state|opp"
    r")\b",
    re.IGNORECASE,
)
QCOM_SCM_MEMORY_RE = re.compile(
    r"\bqcom_scm_assign_mem\b|\bQCOM_SCM_VMID_\w+\b|\bqcom,vmid\b|"
    r"\bVMID\b|\bTrustZone\b|\bnon-HLOS\b|\bsecure[-_ ]?DMA\b|"
    r"\bSMMU\b(?=.{0,80}\b(?:DMA|share|sharing|ownership|assign|assignment|map|mapping)\b)",
    re.IGNORECASE,
)
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
    """Patch changes a DT contract file: binding schema/header, .dts, or .dtsi."""
    return any(DT_RE.search(path) or DT_BINDING_HEADER_RE.search(path) for path in paths)





def uses_of_api(diff_text: str) -> bool:
    """Changed lines call the OF/DT driver API."""
    return bool(OF_API_RE.search(changed_diff_text(diff_text)))


def touches_dt(paths: Iterable[str], diff_text: str) -> bool:
    """Any DT surface — a DT file or OF driver API. Kept for callers/tests."""
    return touches_dt_file(paths) or uses_of_api(diff_text)


def touches_dt_contract_only(paths: Iterable[str]) -> bool:
    """Patch only changes DT schemas/DTS files or dt-bindings headers."""
    path_list = list(paths)
    return bool(path_list) and all(
        DT_RE.search(path) or DT_BINDING_HEADER_RE.search(path)
        for path in path_list
    )


def touches_hardware(paths: Iterable[str], diff_text: str) -> bool:
    """Patch changes hardware-facing code or DT resource contracts."""
    path_list = list(paths)
    changed = changed_diff_text(diff_text)
    if any(HARDWARE_PATH_RE.search(path) for path in path_list) and HARDWARE_TEXT_RE.search(changed):
        return True
    return touches_dt_contract_only(path_list) and bool(HARDWARE_TEXT_RE.search(changed))


def touches_qcom_scm_memory(diff_text: str, message: str, rule_cards: list[dict[str, object]]) -> bool:
    """Patch changes Qualcomm SCM/VMID secure-memory assignment surfaces."""
    if any(card.get("id") == "qcom-scm-vmid-memory-assignment" for card in rule_cards):
        return True
    changed = changed_diff_text(diff_text)
    return bool(QCOM_SCM_MEMORY_RE.search(changed) or QCOM_SCM_MEMORY_RE.search(message))


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
        rule_cards = select_rule_cards(
            skill_dir=Path(__file__).resolve().parents[1],
            paths=changed_files,
            diff_text=diff_text,
            message=commit_body,
        )
        qcom_scm_memory = touches_qcom_scm_memory(diff_text, commit_body, rule_cards)
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
            "qcom_scm_memory": qcom_scm_memory,
            "rule_cards": rule_cards,
            "paths": {
                "diff": f"tmp/patch_{index}_diff.txt",
                "build": f"tmp/patch_{index}_build.txt",
                "dtbinding": f"tmp/patch_{index}_dtbinding.txt",
                "packet": f"tmp/patch_{index}_review_packet.md",
                "packet_json": f"tmp/patch_{index}_review_packet.json",
                "block": f"tmp/patch_{index}_block.html",
            },
        }
        patches.append(patch)

    groups = assign_dependency_groups(patches)

    return {
        "schema": "review-commits.patch-series-manifest.v1",
        "mode": mode,
        "slug": slug,
        "review_base": review_base,
        "review_tip": review_tip,
        "packet_mode": "packet",
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
    parser.add_argument(
        "--packet-mode",
        choices=("packet",),
        default="packet",
        help="Packet-only reviewer artifact mode recorded in the manifest",
    )
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
