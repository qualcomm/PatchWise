# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""pytest entry point for the bug-recall evaluation harness (test set 2).

Uses BUG_COMMITS_2 / BUG_TO_FIXES_2 — 26 bug commits from 2026.

Gated behind PATCHWISE_RUN_EVAL=1 because it shells Docker, calls a paid
embedding API, and requires a kernel tree with the buggy SHAs in history.

Can also be run directly:
    python3 tests/eval/test_eval_2.py --reviews-dir ../pw-tests/ai_reviews ...
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__:
    from .bug_commits import BUG_COMMITS_2, BUG_TO_FIXES_2
    from .run import (
        _DEFAULT_CHROMA_PATH,
        _DEFAULT_EMBEDDING_MODEL,
        _DEFAULT_KERNEL_PATH,
        _DEFAULT_SCOPE_REF,
        _DEFAULT_THRESHOLD,
        _DEFAULT_TOP_K,
        run_pipeline,
    )
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tests.eval.bug_commits import BUG_COMMITS_2, BUG_TO_FIXES_2  # type: ignore[no-redef]
    from tests.eval.run import (  # type: ignore[no-redef]
        _DEFAULT_CHROMA_PATH,
        _DEFAULT_EMBEDDING_MODEL,
        _DEFAULT_KERNEL_PATH,
        _DEFAULT_SCOPE_REF,
        _DEFAULT_THRESHOLD,
        _DEFAULT_TOP_K,
        run_pipeline,
    )

import pytest


def test_eval_pipeline_2(request: pytest.FixtureRequest) -> None:
    if os.environ.get("PATCHWISE_RUN_EVAL") != "1":
        pytest.skip("Set PATCHWISE_RUN_EVAL=1 to run the eval harness")

    kernel_path = Path(os.environ.get("PATCHWISE_EVAL_KERNEL_PATH", str(_DEFAULT_KERNEL_PATH)))
    output_dir_env = os.environ.get("PATCHWISE_EVAL_OUTPUT_DIR")
    output_dir = Path(output_dir_env) if output_dir_env else None
    scope_ref = os.environ.get("PATCHWISE_EVAL_SCOPE_REF", _DEFAULT_SCOPE_REF)
    embedding_model = request.config.getoption("--embedding-model") or os.environ.get("PATCHWISE_EVAL_EMBEDDING_MODEL", _DEFAULT_EMBEDDING_MODEL)
    embedding_provider = request.config.getoption("--embedding-provider") or os.environ.get("PATCHWISE_EVAL_EMBEDDING_PROVIDER")
    top_k = int(os.environ.get("PATCHWISE_EVAL_TOP_K", str(_DEFAULT_TOP_K)))
    threshold = float(os.environ.get("PATCHWISE_EVAL_MATCH_THRESHOLD", str(_DEFAULT_THRESHOLD)))
    force_rerun = os.environ.get("PATCHWISE_EVAL_FORCE_RERUN") == "1"
    patchwise_model = request.config.getoption("--model") or os.environ.get("PATCHWISE_EVAL_MODEL")
    patchwise_provider = request.config.getoption("--provider") or os.environ.get("PATCHWISE_EVAL_PROVIDER")
    reviews_dir_opt = request.config.getoption("--reviews-dir")
    reviews_dir = Path(reviews_dir_opt) if reviews_dir_opt else None
    chroma_path_env = os.environ.get("PATCHWISE_EVAL_CHROMA_PATH")
    chroma_path = Path(chroma_path_env) if chroma_path_env else _DEFAULT_CHROMA_PATH
    judge_enabled = os.environ.get("PATCHWISE_EVAL_DISABLE_JUDGE") != "1"
    judge_model = os.environ.get("PATCHWISE_EVAL_JUDGE_MODEL")
    judge_provider = os.environ.get("PATCHWISE_EVAL_JUDGE_PROVIDER")

    try:
        actual_output_dir = run_pipeline(
            kernel_path=kernel_path,
            output_dir=output_dir,
            scope_ref=scope_ref,
            embedding_model=embedding_model,
            embedding_provider=embedding_provider,
            top_k=top_k,
            threshold=threshold,
            force_rerun=force_rerun,
            patchwise_model=patchwise_model,
            patchwise_provider=patchwise_provider,
            reviews_dir=reviews_dir,
            judge_enabled=judge_enabled,
            judge_model=judge_model,
            judge_provider=judge_provider,
            bug_commits=BUG_COMMITS_2,
            bug_to_fixes=BUG_TO_FIXES_2,
            use_chroma_db=True,
            chroma_path=chroma_path,
        )
    except RuntimeError as e:
        pytest.skip(str(e))

    assert (actual_output_dir / "report.md").exists()
    assert (actual_output_dir / "metrics.json").exists()


if __name__ == "__main__":
    import logging
    from tests.eval.run import _parse_args

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args()
    try:
        run_pipeline(
            kernel_path=args.kernel_path,
            output_dir=args.output_dir,
            scope_ref=args.scope_ref,
            embedding_model=args.embedding_model,
            embedding_provider=args.embedding_provider,
            top_k=args.top_k,
            threshold=args.threshold,
            force_rerun=args.force_rerun,
            patchwise_model=args.model,
            patchwise_provider=args.provider,
            reviews_dir=args.reviews_dir,
            judge_enabled=not args.no_judge,
            judge_model=args.judge_model,
            judge_provider=args.judge_provider,
            bug_commits=BUG_COMMITS_2,
            bug_to_fixes=BUG_TO_FIXES_2,
            use_chroma_db=True,
            chroma_path=_DEFAULT_CHROMA_PATH,
        )
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
