# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Loaders for the kernel review prompts under thirdparty/review-prompts."""

import os
from functools import cache
from pathlib import Path
from typing import Optional

REVIEW_PROMPTS_PATH = (
    Path(__file__).resolve().parents[3] / "thirdparty" / "review-prompts"
)
KERNEL_REVIEW_PROMPTS_PATH = REVIEW_PROMPTS_PATH / "kernel"
SUBSYSTEM_REVIEW_PROMPTS_PATH = KERNEL_REVIEW_PROMPTS_PATH / "subsystem"


@cache
def _load_subsystem_guide(safe_name: str) -> Optional[str]:
    """Read a subsystem guide's content, cached for the process lifetime.

    The guides are immutable on disk, so the first read serves every later
    call across reviews, phases, and critic rounds (the critic re-fetches the
    same guide each round). Returns None when the guide does not exist.
    """
    if os.path.basename(safe_name) != safe_name or not safe_name.endswith(".md"):
        return None
    try:
        with open(SUBSYSTEM_REVIEW_PROMPTS_PATH / safe_name, "r") as f:
            return f.read()
    except FileNotFoundError:
        return None


@cache
def _load_review_prompt(title: str, path: Path) -> str:
    """Read a review-prompts doc as a titled prompt section, cached like the
    subsystem guides."""
    with open(path, "r") as f:
        return f"## {title}:\n\n{f.read()}"


def get_technical_patterns() -> str:
    """The kernel failure taxonomy."""
    return _load_review_prompt(
        "Kernel Technical Patterns", KERNEL_REVIEW_PROMPTS_PATH / "technical-patterns.md"
    )


def get_false_positive_guide() -> str:
    """The prove-or-drop rubric for separating real issues from plausible ones."""
    return _load_review_prompt(
        "False Positive Guide", KERNEL_REVIEW_PROMPTS_PATH / "false-positive-guide.md"
    )


def get_subsystem_index() -> str:
    """The subsystem review guide index (which guides exist + their triggers)."""
    return _load_review_prompt(
        "Subsystem Review Guide Index", SUBSYSTEM_REVIEW_PROMPTS_PATH / "subsystem.md"
    )
