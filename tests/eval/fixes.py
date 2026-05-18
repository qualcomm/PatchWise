# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Hydrate FixCommit records (subject + body + diff) from a SHA mapping."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

@dataclass
class FixCommit:
    sha: str
    subject: str
    body: str


def load_fix_commits(
    bug_to_fix_shas: dict[str, list[str]],
    kernel_path: Path,
) -> dict[str, list[FixCommit]]:
    """Resolve every fix SHA in *bug_to_fix_shas* into a populated FixCommit.

    Each fix is loaded at most once even if it appears under multiple bugs.
    """
    cache: dict[str, FixCommit] = {}
    out: dict[str, list[FixCommit]] = {}
    for bug_sha, fix_shas in bug_to_fix_shas.items():
        out[bug_sha] = []
        for sha in fix_shas:
            if sha not in cache:
                cache[sha] = _load_fix_commit(sha, kernel_path)
            out[bug_sha].append(cache[sha])
    return out


def _load_fix_commit(sha: str, kernel_path: Path) -> FixCommit:
    log_result = subprocess.run(
        ["git", "-C", str(kernel_path), "log", "-1", "--format=%s%n%n%b", sha],
        capture_output=True,
        text=True,
        check=True,
    )
    head, _, body = log_result.stdout.partition("\n\n")
    return FixCommit(sha=sha, subject=head.strip(), body=body.strip())


def load_fix_diff(sha: str, kernel_path: Path, *, max_bytes: int = 12 * 1024) -> str:
    """Return the unified diff for *sha*, truncated to *max_bytes*."""
    result = subprocess.run(
        ["git", "-C", str(kernel_path), "show", "--format=", sha],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout[:max_bytes]
