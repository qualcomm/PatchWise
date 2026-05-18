# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""ChromaDB-backed matching against a pre-built full-commit collection.

Used by test_eval_2.  The collection must be built first with:
    python -m tests.eval.build_db --since 2026-03-01 ...
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .build_db import COLLECTION_NAME
from .embed import DEFAULT_MODEL, embed_texts
from .match import Match
from .parse import Issue

logger = logging.getLogger(__name__)


def _commit_timestamp(sha: str, kernel_path: Path) -> int:
    """Return the Unix commit timestamp for *sha*."""
    return int(subprocess.check_output(
        ["git", "-C", str(kernel_path), "log", "-1", "--format=%ct", sha],
        text=True,
    ).strip())


def match_issues_to_db(
    issues: list[Issue],
    *,
    top_k: int = 10,
    threshold: float = 0.5,
    chroma_path: Path,
    model: str | None = None,
    api_base: str | None = None,
    cache_dir: Path,
    bug_sha: str | None = None,
    kernel_path: Path | None = None,
) -> list[Match]:
    """Query the pre-built ChromaDB collection for each issue.

    Returns all (issue, commit) pairs with similarity >= threshold.
    Raises RuntimeError if the collection does not exist (run build_db first).

    When bug_sha and kernel_path are provided, candidate commits that predate
    the bug commit are filtered out — a fix cannot precede the bug it fixes.
    """
    if not issues:
        return []

    import chromadb

    effective_model = model or DEFAULT_MODEL

    client = chromadb.PersistentClient(path=str(chroma_path))
    existing = [c.name for c in client.list_collections()]
    if COLLECTION_NAME not in existing:
        raise RuntimeError(
            f"ChromaDB collection '{COLLECTION_NAME}' not found at {chroma_path}. "
            "Run `python -m tests.eval.build_db` first."
        )
    collection = client.get_collection(COLLECTION_NAME)
    total = collection.count()
    logger.info("Querying ChromaDB collection '%s' (%d commits)", COLLECTION_NAME, total)

    bug_ts: int | None = None
    if bug_sha and kernel_path:
        bug_ts = _commit_timestamp(bug_sha, kernel_path)

    issue_texts = [i.quoted_diff + "\n\n" + i.prose for i in issues]
    issue_vecs = embed_texts(issue_texts, model=effective_model, api_base=api_base, cache_dir=cache_dir)

    # Cache timestamps for candidate SHAs to avoid redundant git calls.
    ts_cache: dict[str, int] = {}

    def _is_after_bug(sha: str) -> bool:
        if bug_ts is None:
            return True
        if sha not in ts_cache:
            try:
                ts_cache[sha] = _commit_timestamp(sha, kernel_path)
            except (subprocess.CalledProcessError, ValueError):
                return False
        return ts_cache[sha] > bug_ts

    matches: list[Match] = []
    for issue_idx, issue_vec in enumerate(issue_vecs):
        best: dict[str, float] = {}

        results = collection.query(query_embeddings=[issue_vec.tolist()], n_results=top_k)
        for sha, distance in zip(results["ids"][0], results["distances"][0]):
            sim = 1.0 - distance
            if sim > threshold and _is_after_bug(sha):
                if sha not in best or sim > best[sha]:
                    best[sha] = sim

        for sha, sim in best.items():
            matches.append(Match(
                issue_idx=issue_idx,
                fix_sha=sha,
                similarity=sim,
            ))

    return matches
