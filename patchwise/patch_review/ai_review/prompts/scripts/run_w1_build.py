#!/usr/bin/env python3
"""Run a non-interactive kernel W=1 build and reject Kconfig prompt spam."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_INTERACTIVE_KCONFIG_TOKENS = (
    "Restart config...",
    "choice[",
    "Error in reading or end of file.",
)


def has_interactive_kconfig(text: str) -> bool:
    return any(token in text for token in _INTERACTIVE_KCONFIG_TOKENS)


def _run_make(project: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("KCONFIG_NONINTERACTIVE", "1")
    env.setdefault("LANG", "C")
    env.setdefault("LC_ALL", "C")
    return subprocess.run(
        ["make", *args],
        cwd=str(project),
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        env=env,
    )


def _write_output(path: Path, text: str, *, append: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as handle:
        handle.write(text)


def _refresh_config(
    project: Path,
    output: Path,
    *,
    arch: str | None,
    append: bool,
) -> int:
    config_args: list[str] = []
    if arch:
        config_args.append(f"ARCH={arch}")

    config_path = project / ".config"
    refresh_logs: list[str] = []

    if not config_path.exists():
        proc = _run_make(project, [*config_args, "defconfig"])
        refresh_logs.append(proc.stdout + proc.stderr)
        if proc.returncode != 0:
            _write_output(
                output,
                "=== defconfig failed ===\n" + refresh_logs[-1],
                append=append,
            )
            return proc.returncode
        append = True

    proc = _run_make(project, [*config_args, "olddefconfig"])
    refresh_logs.append(proc.stdout + proc.stderr)
    refresh_output = "".join(refresh_logs)
    if proc.returncode != 0:
        _write_output(
            output,
            "=== olddefconfig failed ===\n" + refresh_output,
            append=append,
        )
        return proc.returncode
    if has_interactive_kconfig(refresh_output):
        _write_output(
            output,
            "=== invalid interactive Kconfig output during config refresh ===\n"
            + refresh_output,
            append=append,
        )
        return 2
    return 0


def run_build(
    *,
    project: Path,
    output: Path,
    targets: list[str],
    arch: str | None,
    cross_compile: str | None,
    jobs: int,
    append: bool,
    refresh_config: bool,
) -> int:
    if not targets:
        _write_output(output, "(no build targets provided — build skipped)\n", append=append)
        return 0

    if refresh_config:
        rc = _refresh_config(project, output, arch=arch, append=append)
        if rc != 0:
            return rc
        append = True

    make_args: list[str] = []
    if arch:
        make_args.append(f"ARCH={arch}")
    if cross_compile:
        make_args.append(f"CROSS_COMPILE={cross_compile}")
    make_args.extend([f"-j{jobs}", "W=1", *targets])
    proc = _run_make(project, make_args)
    build_output = proc.stdout + proc.stderr
    _write_output(output, build_output, append=append)
    if proc.returncode != 0:
        return proc.returncode
    if has_interactive_kconfig(build_output):
        _write_output(
            output,
            "\n=== invalid interactive Kconfig output during build ===\n",
            append=True,
        )
        return 2
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True, help="kernel tree path")
    parser.add_argument("--output", type=Path, required=True, help="file to write build output")
    parser.add_argument("--arch", default=None, help="ARCH=<value> for make")
    parser.add_argument("--cross-compile", default=None, help="CROSS_COMPILE=<value> for make")
    parser.add_argument("--jobs", type=int, default=99, help="parallelism for make")
    parser.add_argument("--append", action="store_true", help="append to output instead of overwrite")
    parser.add_argument(
        "--no-refresh-config",
        action="store_true",
        help="skip defconfig/olddefconfig refresh before the build",
    )
    parser.add_argument("targets", nargs="*", help="make targets/directories to build")
    args = parser.parse_args(argv)
    return run_build(
        project=args.project,
        output=args.output,
        targets=args.targets,
        arch=args.arch,
        cross_compile=args.cross_compile,
        jobs=args.jobs,
        append=args.append,
        refresh_config=not args.no_refresh_config,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
