# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Cosine top-K matching of patchwise issues to fix commits."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .embed import embed_texts
from .fixes import FixCommit
from .parse import Issue


@dataclass
class Match:
    issue_idx: int
    fix_sha: str
    similarity: float
    judge_verdict: bool | None = None
    judge_reason: str | None = None
    is_known_fix: bool = False


def match_issues_to_fixes(
    issues: list[Issue],
    fixes: list[FixCommit],
    *,
    top_k: int = 10,
    threshold: float = 0.5,
    cache_dir: Path,
    model: str | None = None,
    api_base: str | None = None,
) -> list[Match]:
    """Return all (issue, fix) pairs with similarity >= threshold, sorted descending.

    top_k is kept for report display (best-N per issue); all above-threshold
    pairs are returned so the judge sees every plausible candidate.
    Returns an empty list when *issues* or *fixes* is empty.
    """
    if not issues or not fixes:
        return []

    issue_texts = [i.quoted_diff + "\n\n" + i.prose for i in issues]
    fix_texts = [f.subject + "\n\n" + f.body for f in fixes]

    issue_vecs = embed_texts(issue_texts, model=model, api_base=api_base, cache_dir=cache_dir)
    fix_vecs = embed_texts(fix_texts, model=model, api_base=api_base, cache_dir=cache_dir)

    # cosine similarity = dot product (vectors are already L2-normalised)
    scores = issue_vecs @ fix_vecs.T  # (n_issues, n_fixes)

    matches: list[Match] = []
    for issue_idx in range(len(issues)):
        row = scores[issue_idx]
        for fix_idx in np.argsort(row)[::-1]:
            sim = float(row[fix_idx])
            if sim <= threshold:
                break
            matches.append(Match(
                issue_idx=issue_idx,
                fix_sha=fixes[fix_idx].sha,
                similarity=sim,
            ))

    return matches
