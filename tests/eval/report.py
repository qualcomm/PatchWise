# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Render report.md and metrics.json from eval results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .fixes import FixCommit
from .match import Match
from .parse import Issue


@dataclass
class BugResult:
    bug_sha: str
    bug_subject: str
    issues: list[Issue]
    fixes: list[FixCommit]
    matches: list[Match]


def generate_report(
    results: list[BugResult],
    *,
    output_dir: Path,
    threshold: float,
    top_k: int,
    scope_ref: str,
    kernel_head: str,
    model: str,
) -> None:
    """Write report.md and metrics.json to *output_dir*."""
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_report_md(results, output_dir=output_dir, threshold=threshold)
    _write_metrics_json(
        results,
        output_dir=output_dir,
        threshold=threshold,
        top_k=top_k,
        scope_ref=scope_ref,
        kernel_head=kernel_head,
        model=model,
    )


# ---------------------------------------------------------------------------
# report.md
# ---------------------------------------------------------------------------

def _write_report_md(results: list[BugResult], *, output_dir: Path, threshold: float) -> None:
    lines: list[str] = []
    lines.append("# Patchwise Bug-Recall Evaluation Report\n")

    # Section 1: Bug Commit Summary
    lines.append("## Bug Commit Summary\n")
    lines.append("| Bug commit | Bug commit subject | Fix commits | Patchwise found ≥1 match? | Top similarity |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in results:
        fix_shas = ", ".join(f"`{f.sha[:12]}`" for f in r.fixes) or "—"
        best_sim = _best_similarity(r.matches)
        any_match = any(_is_matched(m, threshold) for m in r.matches)
        found = "**Yes**" if any_match else "**No**"
        sim_str = f"{best_sim:.3f}" if best_sim is not None else "—"
        lines.append(f"| `{r.bug_sha[:12]}` | {r.bug_subject} | {fix_shas} | {found} | {sim_str} |")
    lines.append("")

    # Section 2: All Fixes: Commits
    lines.append("## All `Fixes:` Commits\n")
    lines.append("| Bug commit | Fix commit | Fix subject | Best matching issue | Similarity | Known fix | Judge |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for r in results:
        for fc in r.fixes:
            best = _best_match_for_fix(r.matches, fc.sha)
            if best is not None and r.issues:
                issue_excerpt = _excerpt(r.issues[best.issue_idx].prose)
                sim_str = f"{best.similarity:.3f}"
                known_str = "✓" if best.is_known_fix else "✗"
                judge_str = _judge_cell(best)
            else:
                issue_excerpt = "—"
                sim_str = "—"
                known_str = "✓"
                judge_str = "—"
            lines.append(
                f"| `{r.bug_sha[:12]}` | `{fc.sha[:12]}` | {fc.subject} | {issue_excerpt} | {sim_str} | {known_str} | {judge_str} |"
            )
    lines.append("")

    # Section 3: Issues That Were Later Fixed
    lines.append("## Patchwise Issues That Were Later Fixed\n")
    lines.append("| Bug commit | Issue excerpt | Best fix match | Similarity | Known fix | Judge reason |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for r in results:
        for issue_idx, issue in enumerate(r.issues):
            best = _best_matched(r.matches, issue_idx, threshold)
            if best is not None:
                known_str = "✓" if best.is_known_fix else "✗"
                lines.append(
                    f"| `{r.bug_sha[:12]}` | {_excerpt(issue.prose)} | `{best.fix_sha[:12]}` | "
                    f"{best.similarity:.3f} | {known_str} | {_excerpt(best.judge_reason or '', 100)} |"
                )
    lines.append("")

    # Section 4: Issues Not Matched
    lines.append("## Patchwise Issues Not Matched\n")
    lines.append("| Bug commit | Issue excerpt | Top similarity | Judge reason |")
    lines.append("| --- | --- | --- | --- |")
    for r in results:
        for issue_idx, issue in enumerate(r.issues):
            if _best_matched(r.matches, issue_idx, threshold) is not None:
                continue
            top = _best_match_for_issue(r.matches, issue_idx)
            sim_str = f"{top.similarity:.3f}" if top is not None else "—"
            reason = _excerpt(top.judge_reason, 100) if top and top.judge_reason else ""
            lines.append(f"| `{r.bug_sha[:12]}` | {_excerpt(issue.prose)} | {sim_str} | {reason} |")
    lines.append("")

    # Section 5: Totals
    lines.append("## Totals\n")
    n_bugs_with_match = sum(
        1 for r in results
        if any(_is_matched(m, threshold) for m in r.matches)
    )
    total_issues = sum(len(r.issues) for r in results)
    total_matched = sum(
        1 for r in results
        for i in range(len(r.issues))
        if _best_matched(r.matches, i, threshold) is not None
    )
    total_fixes = sum(len(r.fixes) for r in results)
    lines.append(f"- Bug commits with ≥1 matched issue: **{n_bugs_with_match} / {len(results)}**")
    lines.append(f"- Total patchwise issues: **{total_issues}**")
    lines.append(f"- Total matched issues: **{total_matched}**")
    n_matched_known = sum(
        1 for r in results
        for i in range(len(r.issues))
        for m in [_best_matched(r.matches, i, threshold)]
        if m is not None and m.is_known_fix
    )
    lines.append(f"  - Matched to a known `Fixes:` commit: **{n_matched_known}**")
    lines.append(f"  - Matched to a semantic-only commit: **{total_matched - n_matched_known}**")
    lines.append(f"- Total fix commits in scope: **{total_fixes}**")
    lines.append("")

    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# metrics.json
# ---------------------------------------------------------------------------

def _write_metrics_json(
    results: list[BugResult],
    *,
    output_dir: Path,
    threshold: float,
    top_k: int,
    scope_ref: str,
    kernel_head: str,
    model: str,
) -> None:
    per_bug: dict[str, Any] = {}
    for r in results:
        n_matched = sum(
            1 for i in range(len(r.issues))
            if _best_matched(r.matches, i, threshold) is not None
        )
        fix_shas = {f.sha for f in r.fixes}
        n_fixes_with_match = len({
            m.fix_sha for m in r.matches
            if m.fix_sha in fix_shas and _is_matched(m, threshold)
        })
        per_bug[r.bug_sha] = {
            "n_issues": len(r.issues),
            "n_issues_matched": n_matched,
            "n_fixes": len(r.fixes),
            "n_fixes_with_match": n_fixes_with_match,
            "matches": [
                {
                    "issue_idx": m.issue_idx,
                    "fix_sha": m.fix_sha,
                    "similarity": m.similarity,
                    "is_known_fix": m.is_known_fix,
                    "judge_verdict": m.judge_verdict,
                    "judge_reason": m.judge_reason,
                }
                for m in r.matches
            ],
        }

    n_bugs_with_match = sum(
        1 for r in results
        if any(_is_matched(m, threshold) for m in r.matches)
    )
    total_issues = sum(len(r.issues) for r in results)
    total_matched = sum(d["n_issues_matched"] for d in per_bug.values())
    total_fixes = sum(len(r.fixes) for r in results)

    metrics: dict[str, Any] = {
        "config": {
            "model": model,
            "threshold": threshold,
            "top_k": top_k,
            "scope_ref": scope_ref,
            "kernel_head": kernel_head,
        },
        "per_bug_commit": per_bug,
        "overall": {
            "bug_commits_with_at_least_one_match": n_bugs_with_match,
            "total_issues": total_issues,
            "total_matched": total_matched,
            "total_fixes": total_fixes,
        },
    }

    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _is_matched(m: Match, threshold: float) -> bool:
    """Binary match decision: prefer judge verdict, fall back to similarity threshold."""
    if m.judge_verdict is not None:
        return m.judge_verdict
    return m.similarity >= threshold


def _best_matched(matches: list[Match], issue_idx: int, threshold: float) -> Match | None:
    """Best matched candidate for *issue_idx*, ranked by similarity. None if no match."""
    candidates = [m for m in matches if m.issue_idx == issue_idx and _is_matched(m, threshold)]
    if not candidates:
        return None
    return max(candidates, key=lambda m: m.similarity)


def _best_similarity(matches: list[Match]) -> float | None:
    if not matches:
        return None
    return max(m.similarity for m in matches)


def _best_match_for_issue(matches: list[Match], issue_idx: int) -> Match | None:
    candidates = [m for m in matches if m.issue_idx == issue_idx]
    if not candidates:
        return None
    return max(candidates, key=lambda m: m.similarity)


def _best_match_for_fix(matches: list[Match], fix_sha: str) -> Match | None:
    candidates = [m for m in matches if m.fix_sha == fix_sha]
    if not candidates:
        return None
    return max(candidates, key=lambda m: m.similarity)


def _judge_cell(m: Match) -> str:
    if m.judge_verdict is None:
        return "—"
    return "✓" if m.judge_verdict else "✗"


def _excerpt(text: str, max_len: int = 120) -> str:
    single = text.replace("\n", " ").strip()
    if len(single) <= max_len:
        return single
    return single[:max_len] + "…"
