# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Subprocess wrapper around the patchwise CLI for AiCodeReview runs."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path


def run_aicodereview(
    bug_sha: str,
    *,
    kernel_path: Path,
    output_dir: Path,
    force: bool = False,
    model: str | None = None,
    provider: str | None = None,
) -> Path:
    """Run patchwise AiCodeReview for *bug_sha* and return the aicodereview.txt path.

    Results are cached: if the output file already exists and *force* is False,
    the existing file is returned immediately.
    """
    commit_dir = output_dir / bug_sha
    review_file = commit_dir / "aicodereview.txt"

    if review_file.exists() and not force:
        return review_file

    commit_dir.mkdir(parents=True, exist_ok=True)

    patchwise_cmd = _resolve_patchwise_cmd()
    command = [
        *patchwise_cmd,
        "--reviews",
        "AiCodeReview",
        "--commits",
        bug_sha,
        "--repo-path",
        str(kernel_path),
        "--output-dir",
        str(output_dir),
    ]
    if model:
        command += ["--model", model]
    if provider:
        command += ["--provider", provider]

    log_file = commit_dir / "patchwise_run.log"
    rendered = shlex.join(command)

    env = os.environ.copy()
    if "PATCHWISE_SANDBOX_PATH" not in env:
        env["PATCHWISE_SANDBOX_PATH"] = str(_repo_root() / "sandbox")

    with log_file.open("w", encoding="utf-8") as stream:
        stream.write(f"$ {rendered}\n\n")
        stream.flush()

        process = subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(f"[{bug_sha[:12]}] {line}")
            stream.write(line)

        return_code = process.wait()

    if return_code != 0:
        raise RuntimeError(
            f"patchwise exited {return_code} for {bug_sha[:12]}; see {log_file}"
        )

    return review_file


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_patchwise_cmd() -> list[str]:
    candidate = Path(sys.executable).with_name("patchwise")
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return [str(candidate)]
    raise FileNotFoundError(
        f"'patchwise' not found next to sys.executable ({sys.executable}). "
        "Activate the intended venv."
    )
