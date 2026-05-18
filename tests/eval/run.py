# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Standalone entry point for the bug-recall eval harness.

Usage:
    python -m tests.eval \
        --reviews-dir ../pw-tests/ai_reviews \
        --embedding-model openai/qwen3-embedding-0.6b \
        --embedding-provider https://qpilot-api.qualcomm.com/v1
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .bug_commits import BUG_COMMITS, BUG_TO_FIXES, BUG_COMMITS_2, BUG_TO_FIXES_2
from .fixes import load_fix_commits, load_fix_diff
from .judge import judge_matches_batch
from .match import Match, match_issues_to_fixes
from .match_chroma import match_issues_to_db
from .parse import Issue, parse_issues
from .report import BugResult, generate_report
from .run_aicodereview import run_aicodereview

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_KERNEL_PATH = _REPO_ROOT / "tests" / "linux"
_OUTPUT_BASE_DIR = _REPO_ROOT / "tests" / "eval" / "output"
_DEFAULT_CHROMA_PATH = _REPO_ROOT / "tests" / "eval" / "chroma"
_DEFAULT_SCOPE_REF = "patchwise-linux-next-stable"
_DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
_DEFAULT_TOP_K = 10
_DEFAULT_THRESHOLD = 0.50


def _make_output_dir(patchwise_model: str | None) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_model = re.sub(r"[^A-Za-z0-9._-]", "_", patchwise_model or "default")
    return _OUTPUT_BASE_DIR / f"{ts}-{safe_model}"


def run_pipeline(
    *,
    kernel_path: Path,
    output_dir: Path | None = None,
    scope_ref: str,
    embedding_model: str,
    embedding_provider: str | None,
    top_k: int,
    threshold: float,
    force_rerun: bool,
    patchwise_model: str | None,
    patchwise_provider: str | None,
    reviews_dir: Path | None,
    judge_enabled: bool = True,
    judge_model: str | None = None,
    judge_provider: str | None = None,
    bug_commits: list[str] | None = None,
    bug_to_fixes: dict[str, list[str]] | None = None,
    use_chroma_db: bool = False,
    chroma_path: Path | None = None,
) -> Path:
    if output_dir is None:
        logger.info("Output directory: %s", output_dir)

    if bug_commits is None:
        bug_commits = BUG_COMMITS
    if bug_to_fixes is None:
        bug_to_fixes = BUG_TO_FIXES

    effective_judge_model = judge_model
    effective_judge_provider = judge_provider
    if judge_enabled and not effective_judge_model:
        raise RuntimeError(
            "LLM judge is enabled but --judge-model is not set. "
            "Pass --judge-model (and usually --judge-provider) explicitly, "
            "or pass --no-judge to fall back to similarity-threshold matching."
        )
    if reviews_dir is None and shutil.which("docker") is None:
        raise RuntimeError("docker not found on PATH (required when --reviews-dir is not set)")

    if not kernel_path.exists():
        raise RuntimeError(f"Kernel tree not found at {kernel_path}")

    missing = [
        sha[:12] for sha in bug_commits
        if subprocess.run(
            ["git", "-C", str(kernel_path), "cat-file", "-e", sha],
            capture_output=True,
        ).returncode != 0
    ]
    if missing:
        raise RuntimeError(f"Kernel tree missing SHAs: {', '.join(missing)}")

    embeddings_dir = output_dir / "embeddings"
    embeddings_dir.mkdir(parents=True, exist_ok=True)
    judge_cache_dir = output_dir / "judge"
    judge_cache_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    head_result = subprocess.run(
        ["git", "-C", str(kernel_path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    kernel_head = head_result.stdout.strip()

    logger.info("Loading %d fix commits from static mapping...",
                sum(len(v) for v in bug_to_fixes.values()))
    fixes_by_bug = load_fix_commits(bug_to_fixes, kernel_path)

    results = []
    for bug_sha in bug_commits:
        if reviews_dir is not None:
            review_file = reviews_dir / bug_sha / "aicodereview.txt"
            if not review_file.exists():
                logger.warning("No review file for %s at %s, skipping", bug_sha[:12], review_file)
                continue
        else:
            ai_reviews_dir = output_dir / "ai_reviews"
            ai_reviews_dir.mkdir(parents=True, exist_ok=True)
            review_file = run_aicodereview(
                bug_sha,
                kernel_path=kernel_path,
                output_dir=ai_reviews_dir,
                force=force_rerun,
                model=patchwise_model,
                provider=patchwise_provider,
            )

        issues = parse_issues(review_file)
        print(f"\nProcessing {bug_sha}:\n", flush=True)
        if issues:
            print("Issues:\n", flush=True)
            for i, issue in enumerate(issues, 1):
                body = issue.quoted_diff
                if issue.prose:
                    body = body + "\n\n" + issue.prose if body else issue.prose
                print(f"{i}.", flush=True)
                print("```", flush=True)
                print(body, flush=True)
                print("```\n", flush=True)
        else:
            print("Issues: (none)\n", flush=True)

        fixes = fixes_by_bug.get(bug_sha, [])
        if use_chroma_db:
            effective_chroma_path = chroma_path or _DEFAULT_CHROMA_PATH
            matches = match_issues_to_db(
                issues,
                top_k=top_k,
                threshold=threshold,
                chroma_path=effective_chroma_path,
                model=embedding_model,
                api_base=embedding_provider,
                cache_dir=embeddings_dir,
                bug_sha=bug_sha,
                kernel_path=kernel_path,
            )
            # Fallback: directly score any known fix commits that ChromaDB didn't
            # return, so ranking gaps don't silently hide ground-truth fixes.
            if fixes:
                db_matched_shas = {m.fix_sha for m in matches}
                missing_fixes = [f for f in fixes if f.sha not in db_matched_shas]
                if missing_fixes:
                    fallback = match_issues_to_fixes(
                        issues, missing_fixes,
                        top_k=top_k,
                        threshold=threshold,
                        cache_dir=embeddings_dir,
                        model=embedding_model,
                        api_base=embedding_provider,
                    )
                    matches = matches + fallback
        else:
            matches = match_issues_to_fixes(
                issues, fixes,
                top_k=top_k,
                threshold=threshold,
                cache_dir=embeddings_dir,
                model=embedding_model,
                api_base=embedding_provider,
            )

        known_fix_shas = {f.sha for f in fixes}
        for m in matches:
            m.is_known_fix = m.fix_sha in known_fix_shas

        if judge_enabled:
            _judge_matches(
                matches, issues, fixes, kernel_path,
                judge_model=effective_judge_model,
                judge_provider=effective_judge_provider,
                cache_dir=judge_cache_dir,
                bug_sha=bug_sha,
            )

        log_r = subprocess.run(
            ["git", "-C", str(kernel_path), "log", "-1", "--format=%s", bug_sha],
            capture_output=True, text=True, check=True,
        )
        results.append(BugResult(
            bug_sha=bug_sha,
            bug_subject=log_r.stdout.strip(),
            issues=issues,
            fixes=fixes,
            matches=matches,
        ))

    generate_report(
        results,
        output_dir=output_dir,
        threshold=threshold,
        top_k=top_k,
        scope_ref=scope_ref,
        kernel_head=kernel_head,
        model=embedding_model,
    )
    logger.info("Report: %s", output_dir / "report.md")
    logger.info("Metrics: %s", output_dir / "metrics.json")
    return output_dir


def _judge_matches(
    matches: list[Match],
    issues: list[Issue],
    fixes: list,
    kernel_path: Path,
    *,
    judge_model: str,
    judge_provider: str | None,
    cache_dir: Path,
    bug_sha: str,
) -> None:
    """Annotate each Match in *matches* with judge_verdict / judge_reason in place."""
    if not matches:
        return

    from .fixes import FixCommit, _load_fix_commit
    fix_by_sha: dict[str, FixCommit] = {f.sha: f for f in fixes}
    diff_cache: dict[str, str] = {}

    for m in matches:
        if m.fix_sha not in fix_by_sha:
            fix_by_sha[m.fix_sha] = _load_fix_commit(m.fix_sha, kernel_path)
        fix = fix_by_sha[m.fix_sha]
        if fix.sha not in diff_cache:
            diff_cache[fix.sha] = load_fix_diff(fix.sha, kernel_path)

    pairs = [
        (
            (issues[m.issue_idx].quoted_diff + "\n\n" + issues[m.issue_idx].prose).strip(),
            fix_by_sha[m.fix_sha].subject,
            fix_by_sha[m.fix_sha].body,
            diff_cache[m.fix_sha],
        )
        for m in matches
    ]

    verdicts = judge_matches_batch(
        pairs,
        model=judge_model,
        api_base=judge_provider,
        cache_dir=cache_dir,
    )

    for m, verdict in zip(matches, verdicts):
        m.judge_verdict = verdict.matches
        m.judge_reason = verdict.reason
        logger.info(
            "judge: %s issue#%d <-> %s sim=%.3f -> %s (%s)",
            bug_sha[:12], m.issue_idx, m.fix_sha[:12], m.similarity,
            "MATCH" if verdict.matches else "no",
            verdict.reason[:80],
        )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bug-recall eval harness for patchwise AiCodeReview.")
    p.add_argument("--kernel-path", type=Path, default=_DEFAULT_KERNEL_PATH)
    p.add_argument("--output-dir", type=Path, default=None,
                   help="output directory (default: tests/eval/output/<timestamp>-<model>)")
    p.add_argument("--scope-ref", default=_DEFAULT_SCOPE_REF)
    p.add_argument("--embedding-model", default=_DEFAULT_EMBEDDING_MODEL)
    p.add_argument("--embedding-provider", default=None)
    p.add_argument("--top-k", type=int, default=_DEFAULT_TOP_K)
    p.add_argument("--threshold", type=float, default=_DEFAULT_THRESHOLD)
    p.add_argument("--force-rerun", action="store_true")
    p.add_argument("--model", default=None, help="--model passed to patchwise AiCodeReview")
    p.add_argument("--provider", default=None, help="--provider passed to patchwise AiCodeReview")
    p.add_argument("--reviews-dir", type=Path, default=None,
                   help="use existing aicodereview.txt files instead of running patchwise")
    p.add_argument("--no-judge", action="store_true",
                   help="skip LLM-as-judge; report uses only similarity threshold")
    p.add_argument("--judge-model", default=None,
                   help="model used by the LLM judge (required unless --no-judge)")
    p.add_argument("--judge-provider", default=None,
                   help="api_base passed to litellm for the judge")
    return p.parse_args()


if __name__ == "__main__":
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
        )
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
