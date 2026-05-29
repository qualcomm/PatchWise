#!/usr/bin/env python3
"""Run review-commits maintainer preflight checks.

This script is intended for skill/server edits before deployment. It is not part
of the per-review hot path; runtime review quality is enforced by the packet
workflow (assemble_review_packet.py + validate_review_packet.py) and the series
manifest validator.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


@dataclass(frozen=True)
class Paths:
    skill_dir: Path
    repo_root: Path
    scripts_dir: Path
    server_dir: Path


def infer_paths(script_path: Path) -> Paths:
    skill_dir = script_path.resolve().parents[1]
    repo_root = skill_dir.parents[1]
    return Paths(
        skill_dir=skill_dir,
        repo_root=repo_root,
        scripts_dir=skill_dir / "scripts",
        server_dir=repo_root / "server",
    )


def command_text(command: Iterable[object]) -> str:
    return " ".join(str(item) for item in command)


def print_block(text: str, *, stream: object = sys.stdout) -> None:
    stripped = text.strip()
    if stripped:
        print(stripped, file=stream)


def _load_module(paths: Paths, script: str, label: str) -> object:
    """Load a script as a module; print FAIL + exit on import error."""
    spec = importlib.util.spec_from_file_location(label, paths.scripts_dir / script)
    if spec is None or spec.loader is None:
        print(f"{FAIL}: {label} (cannot load {script})", file=sys.stderr)
        raise SystemExit(1)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _report_failures(label: str, failures: list[str]) -> None:
    """Print FAIL + each failure line and raise SystemExit(1), or print PASS."""
    if failures:
        print(f"{FAIL}: {label}", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        raise SystemExit(1)
    print(f"{PASS}: {label}\n")


def run_check(label: str, command: list[object], *, cwd: Path) -> None:
    print(f"==> {label}")
    print(f"$ {command_text(command)}")
    result = subprocess.run(
        [str(item) for item in command],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        print_block(result.stdout)
        print(f"{PASS}: {label}\n")
        return

    print_block(result.stdout)
    print_block(result.stderr, stream=sys.stderr)
    print(f"{FAIL}: {label} (exit {result.returncode})", file=sys.stderr)
    raise SystemExit(result.returncode)


def skill_python_files(paths: Paths) -> list[Path]:
    return sorted(paths.scripts_dir.glob("*.py"))


def server_python_files(paths: Paths) -> list[Path]:
    if not paths.server_dir.is_dir():
        return []
    files = sorted((paths.server_dir / "patch_review").glob("*.py"))
    test_runner = paths.server_dir / "test_review_runner.py"
    if test_runner.is_file():
        files.append(test_runner)
    return files


def py_compile(paths: Paths, *, include_server: bool) -> None:
    files = skill_python_files(paths)
    if include_server:
        files.extend(server_python_files(paths))
    if not files:
        print(f"{SKIP}: python compile (no Python files found)\n")
        return
    run_check(
        "python compile",
        [sys.executable, "-m", "py_compile", *files],
        cwd=paths.repo_root,
    )


def verify_validator_feedback_contract(paths: Paths) -> None:
    required = {
        paths.skill_dir / "refs" / "validator-feedback.md": [
            "# Validator Feedback Tracker",
            "## Triage Workflow",
            "## Entry Format",
            "Validator check: check_name",
            "False-positive guard:",
        ],
        paths.skill_dir / "refs" / "validator-rules.md": [
            "refs/validator-feedback.md",
        ],
        paths.skill_dir / "refs" / "orchestrator-workflow.md": [
            "refs/validator-feedback.md",
        ],
    }

    missing: list[str] = []
    for path, markers in required.items():
        if not path.is_file():
            missing.append(f"missing file: {path.relative_to(paths.repo_root)}")
            continue
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in text:
                missing.append(f"{path.relative_to(paths.repo_root)} missing marker: {marker}")

    if missing:
        print(f"{FAIL}: validator feedback contract", file=sys.stderr)
        for item in missing:
            print(f"- {item}", file=sys.stderr)
        raise SystemExit(1)

    print(f"{PASS}: validator feedback contract\n")


def run_packet_flow_smoke(paths: Paths) -> None:
    """End-to-end smoke test of the rule-trigger packet workflow.

    Builds a throwaway git repo with one base commit and one review commit that
    touches a driver and a DT binding, then runs the full packet pipeline:
    prepare_patch_series -> validate_series_manifest -> assemble_review_packet
    -> validate_review_packet.  This is the exact flow the deep-review daemon
    drives, so a green run here proves the rule-trigger workflow is intact.
    """

    def git(project: Path, *args: str) -> None:
        env = dict(os.environ)
        env.update(
            GIT_AUTHOR_NAME="self-check",
            GIT_AUTHOR_EMAIL="self-check@example.com",
            GIT_COMMITTER_NAME="self-check",
            GIT_COMMITTER_EMAIL="self-check@example.com",
        )
        result = subprocess.run(
            ["git", *args],
            cwd=str(project),
            text=True,
            capture_output=True,
            env=env,
        )
        if result.returncode != 0:
            print_block(result.stdout)
            print_block(result.stderr, stream=sys.stderr)
            print(f"{FAIL}: packet flow smoke (git {args[0]})", file=sys.stderr)
            raise SystemExit(result.returncode)

    def run_script(project: Path, script: str, *args: object) -> None:
        result = subprocess.run(
            [sys.executable, str(paths.scripts_dir / script), *map(str, args)],
            cwd=str(project),
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            print_block(result.stdout)
            print_block(result.stderr, stream=sys.stderr)
            print(f"{FAIL}: packet flow smoke ({script})", file=sys.stderr)
            raise SystemExit(result.returncode)

    with tempfile.TemporaryDirectory(prefix="review_skill_packet_") as tmp:
        project = Path(tmp)
        git(project, "init", "-q")

        driver = project / "drivers" / "misc" / "demo.c"
        driver.parent.mkdir(parents=True)
        driver.write_text(
            "#include <linux/module.h>\n"
            "static int demo_probe(struct platform_device *pdev)\n"
            "{\n\treturn 0;\n}\n",
            encoding="utf-8",
        )
        binding = (
            project
            / "Documentation"
            / "devicetree"
            / "bindings"
            / "misc"
            / "vendor,demo.yaml"
        )
        binding.parent.mkdir(parents=True)
        binding.write_text("title: Demo\n", encoding="utf-8")
        git(project, "add", "-A")
        git(project, "commit", "-q", "-m", "demo: base")
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project),
            text=True,
            capture_output=True,
        ).stdout.strip()

        driver.write_text(
            "#include <linux/module.h>\n"
            "#include <linux/of.h>\n"
            "static const struct of_device_id demo_of_match[] = {\n"
            '\t{ .compatible = "vendor,demo" },\n'
            "\t{ }\n"
            "};\n"
            "MODULE_DEVICE_TABLE(of, demo_of_match);\n"
            "static int demo_probe(struct platform_device *pdev)\n"
            "{\n"
            "\tvoid *buf = devm_kzalloc(&pdev->dev, 16, GFP_KERNEL);\n"
            "\tif (!buf)\n\t\treturn -ENOMEM;\n"
            "\treturn 0;\n"
            "}\n",
            encoding="utf-8",
        )
        git(project, "add", "-A")
        git(project, "commit", "-q", "-m", "demo: add of_match table and probe alloc")
        tip = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project),
            text=True,
            capture_output=True,
        ).stdout.strip()

        tmp_dir = project / "tmp"
        tmp_dir.mkdir()
        slug = "selfcheck_packet"
        manifest = tmp_dir / f"series_{slug}_manifest.json"
        commits = tmp_dir / f"commits_{slug}.txt"
        commits.write_text(f"{tip}\n", encoding="utf-8")
        packet = tmp_dir / "patch_1_review_packet.md"
        packet_json = tmp_dir / "patch_1_review_packet.json"

        run_script(
            project,
            "prepare_patch_series.py",
            "--project", project,
            "--mode", "A",
            "--slug", slug,
            "--output", manifest,
            "--review-base", base,
            "--review-tip", tip,
            "--commits-file", commits,
        )
        run_script(
            project,
            "validate_series_manifest.py",
            manifest,
            "--project", project,
            "--mode", "A",
            "--slug", slug,
            "--review-base", base,
            "--review-tip", tip,
        )
        run_script(
            project,
            "assemble_review_packet.py",
            "--skill-dir", paths.skill_dir,
            "--manifest", manifest,
            "--patch", "1",
            "--project", project,
            "--output", packet,
            "--json-output", packet_json,
        )
        run_script(
            project,
            "validate_review_packet.py",
            packet,
            "--skill-dir", paths.skill_dir,
            "--json", packet_json,
        )

        metadata = json.loads(packet_json.read_text(encoding="utf-8"))
        active_cards = metadata.get("rule_cards", [])
        if not active_cards:
            print(
                f"{FAIL}: packet flow smoke — no rule cards triggered for an "
                "of_match/devm_kzalloc + DT binding patch",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print(
            f"{PASS}: packet flow (prepare -> manifest -> assemble -> validate), "
            f"{len(active_cards)} rule cards triggered\n"
        )


def verify_dtb_target_resolver(paths: Paths) -> None:
    with tempfile.TemporaryDirectory(prefix="review_skill_dtb_targets_") as tmp:
        project = Path(tmp)
        dts_dir = project / "arch" / "arm64" / "boot" / "dts" / "vendor"
        dts_dir.mkdir(parents=True)
        (dts_dir / "Makefile").write_text(
            "dtb-y += board-a.dtb\n",
            encoding="utf-8",
        )
        (dts_dir / "common.dtsi").write_text(
            "/* shared include */\n",
            encoding="utf-8",
        )
        (dts_dir / "board-a.dts").write_text(
            '#include "common.dtsi"\n',
            encoding="utf-8",
        )
        (dts_dir / "board-b.dts").write_text(
            '#include "common.dtsi"\n',
            encoding="utf-8",
        )

        patch_common = project / "patch-common.diff"
        patch_common.write_text(
            "+++ b/arch/arm64/boot/dts/vendor/common.dtsi\n",
            encoding="utf-8",
        )
        result_common = subprocess.run(
            [
                sys.executable,
                paths.scripts_dir / "resolve_dtb_targets.py",
                "--project",
                project,
                "--patch-file",
                patch_common,
            ],
            cwd=str(paths.repo_root),
            text=True,
            capture_output=True,
        )
        if result_common.returncode != 0:
            print_block(result_common.stdout)
            print_block(result_common.stderr, stream=sys.stderr)
            print(f"{FAIL}: dtb target resolver smoke (shared dtsi case)", file=sys.stderr)
            raise SystemExit(result_common.returncode)
        common_targets = [line for line in result_common.stdout.splitlines() if line.strip()]
        expected_common = ["arch/arm64/boot/dts/vendor/board-a.dtb"]
        if common_targets != expected_common:
            print(
                f"{FAIL}: dtb target resolver smoke (shared dtsi case)\n"
                f"expected: {expected_common}\n"
                f"actual:   {common_targets}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print(f"{PASS}: dtb target resolver keeps only declared consumer DTBs")

        patch_direct = project / "patch-direct.diff"
        patch_direct.write_text(
            "+++ b/arch/arm64/boot/dts/vendor/board-b.dts\n",
            encoding="utf-8",
        )
        result_direct = subprocess.run(
            [
                sys.executable,
                paths.scripts_dir / "resolve_dtb_targets.py",
                "--project",
                project,
                "--patch-file",
                patch_direct,
            ],
            cwd=str(paths.repo_root),
            text=True,
            capture_output=True,
        )
        if result_direct.returncode != 0:
            print_block(result_direct.stdout)
            print_block(result_direct.stderr, stream=sys.stderr)
            print(f"{FAIL}: dtb target resolver smoke (undeclared direct dts case)", file=sys.stderr)
            raise SystemExit(result_direct.returncode)
        direct_targets = [line for line in result_direct.stdout.splitlines() if line.strip()]
        if direct_targets:
            print(
                f"{FAIL}: dtb target resolver smoke (undeclared direct dts case)\n"
                f"expected: []\n"
                f"actual:   {direct_targets}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print(f"{PASS}: dtb target resolver skips undeclared direct DTS targets\n")


def run_server_tests(paths: Paths, *, skip_server: bool, full: bool) -> None:
    test_runner = paths.server_dir / "test_review_runner.py"
    if skip_server:
        print(f"{SKIP}: server regression tests (--skip-server)\n")
        return
    if not full:
        print(f"{SKIP}: server regression tests (use --full to run)\n")
        return
    if not test_runner.is_file():
        print(f"{SKIP}: server regression tests ({test_runner} not found)\n")
        return
    run_check(
        "server regression tests",
        [sys.executable, test_runner],
        cwd=paths.repo_root,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--quick",
        action="store_true",
        help="Run quick preflight checks only. This is the default.",
    )
    mode.add_argument(
        "--full",
        action="store_true",
        help="Also run server/test_review_runner.py when the server tree exists.",
    )
    parser.add_argument(
        "--skip-server",
        action="store_true",
        help="Skip server Python compilation and server regression tests.",
    )
    parser.add_argument(
        "--skill-dir",
        type=Path,
        default=None,
        help="Override path to skills/review-commits for standalone validation.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    paths = infer_paths(Path(__file__))
    if args.skill_dir is not None:
        skill_dir = args.skill_dir.expanduser().resolve()
        repo_root = skill_dir.parents[1] if len(skill_dir.parents) > 1 else skill_dir.parent
        paths = Paths(
            skill_dir=skill_dir,
            repo_root=repo_root,
            scripts_dir=skill_dir / "scripts",
            server_dir=repo_root / "server",
        )

    if not paths.skill_dir.is_dir():
        print(f"{FAIL}: skill directory not found: {paths.skill_dir}", file=sys.stderr)
        return 2

    full = bool(args.full)
    print(f"review-commits self-check: {paths.skill_dir}")
    print(f"mode: {'full' if full else 'quick'}\n")

    include_server_compile = paths.server_dir.is_dir() and not args.skip_server
    py_compile(paths, include_server=include_server_compile)
    run_check(
        "review constants contract",
        [
            sys.executable,
            paths.scripts_dir / "validate_review_constants.py",
            "--skill-dir",
            paths.skill_dir,
        ],
        cwd=paths.repo_root,
    )
    run_check(
        "ref classification contract",
        [
            sys.executable,
            paths.scripts_dir / "validate_ref_classification.py",
            "--skill-dir",
            paths.skill_dir,
        ],
        cwd=paths.repo_root,
    )
    verify_validator_feedback_contract(paths)
    verify_dtb_target_resolver(paths)
    run_packet_flow_smoke(paths)
    run_server_tests(paths, skip_server=args.skip_server, full=full)

    print("review-commits self-check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
