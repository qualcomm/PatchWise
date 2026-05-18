# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Parse aicodereview.txt into structured Issue records."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Issue:
    quoted_diff: str
    prose: str


def parse_issues(review_file: Path) -> list[Issue]:
    """Split *review_file* into a list of Issue records.

    Each issue is a ``> ``-prefixed quoted-diff block followed by the prose
    paragraph(s) that describe it.  The sentinel ``No issues found.`` returns
    an empty list.  Trailing quote blocks with no prose are dropped.
    """
    text = review_file.read_text(encoding="utf-8")

    if text.strip() == "No issues found.":
        return []

    paragraphs = _split_paragraphs(text)
    return _group_into_issues(paragraphs)


def _split_paragraphs(text: str) -> list[str]:
    """Split text on blank lines, preserving non-empty paragraphs."""
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                blocks.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _is_quote_block(paragraph: str) -> bool:
    return all(line.startswith("> ") or line == ">" for line in paragraph.splitlines())


def _group_into_issues(paragraphs: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    i = 0
    while i < len(paragraphs):
        if _is_quote_block(paragraphs[i]):
            quote = paragraphs[i]
            prose_parts: list[str] = []
            i += 1
            while i < len(paragraphs) and not _is_quote_block(paragraphs[i]):
                prose_parts.append(paragraphs[i])
                i += 1
            prose = "\n\n".join(prose_parts)
            if prose:
                issues.append(Issue(quoted_diff=quote, prose=prose))
        else:
            i += 1
    return issues
