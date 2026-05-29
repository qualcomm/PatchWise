#!/usr/bin/env python3
"""Entry-point for the review-commits structural validator.

This is the CLI front-end.  All check logic lives in _review_checks.py;
the data model lives in _review_model.py.  This file contains only:
  - run_block(), run_full(), main() — the CLI orchestration
  - Re-exports of every public symbol so callers importing this module
    by name (e.g. test_review_runner.py) still find them here.

Usage:
  validate_review.py <report.html>
  validate_review.py --block-file <patch_N_block.html> …
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# Ensure this script's own directory is on sys.path so sibling modules
# (_review_model, _review_checks) can be imported regardless of how this
# file is invoked (CLI, importlib.util.spec_from_file_location, etc.).
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from pathlib import Path
from typing import Optional

# Re-export everything from the check modules so that callers which
# import validate_review.py as a module (e.g. via importlib in tests)
# can still access top-level symbols like REMEDIATION, check_gate_traces, etc.
from _review_model import *   # noqa: F401,F403
from _review_checks import *  # noqa: F401,F403
# Explicit re-export of private helpers used by run_block / run_full / main
# (import * skips names with leading underscores by default)
from _review_checks import (  # noqa: F401
    _infer_patch_number,
    _load_evidence_dir,
    _load_evidence_manifest,
    _load_patch_corpus,
    _load_patch_file,
    _print_violations,
    _report_only_violations,
    _source_aware_violations,
    _tests_text_from,
)
# Re-export private names that test code accesses directly on the module.
from _review_model import (  # noqa: F401
    _SPARSE_DISABLED_MARKER,
    _RUNTIME_CONFIG_SCHEMA,
)
from _review_checks import (  # noqa: F401
    _load_runtime_config,
)
def run_block(
    block_file: Path,
    tests_path: Optional[Path],
    patch_file: Optional[Path] = None,
    prompt_file: Optional[Path] = None,
    build_file: Optional[Path] = None,
    evidence_file: Optional[Path] = None,
    require_patches: bool = False,
    source_root: Optional[Path] = None,
    packet_file: Optional[Path] = None,
    runtime_config: Optional[Path] = None,
    sparse_file: Optional[Path] = None,
    output_format: str = "human",
) -> int:
    html = block_file.read_text(encoding="utf-8", errors="replace")
    patch_number = _infer_patch_number(block_file, html)
    report = parse_block_fragment(html, block_index=patch_number - 1)
    tests_text = _tests_text_from(tests_path)
    tmp_dir = block_file.parent
    if tests_path is not None:
        tmp_dir = tests_path.parent
    if build_file is not None:
        tmp_dir = build_file.parent

    violations: list[Violation] = []
    if len(report.blocks) != 1:
        violations.append(Violation(
            "block_fragment",
            str(block_file),
            f"block-mode validation expects exactly one commit-block, found {len(report.blocks)}",
        ))
    violations.extend(check_build_break_order(report, tests_text, require_banner=False))
    violations.extend(check_build_artifact_validity(report, tmp_dir))
    violations.extend(_report_only_violations(report))
    violations.extend(check_prompt_file(
        prompt_file=prompt_file,
        block_file=block_file,
        patch_number=patch_number,
        tests_path=tests_path,
        build_file=build_file,
        evidence_file=evidence_file,
        runtime_config=runtime_config,
    ))
    violations.extend(check_packet_file(
        packet_file=packet_file,
        patch_number=patch_number,
    ))
    # Derive packet JSON path from the .md packet file for attestation checks.
    packet_json = None
    if packet_file is not None:
        candidate = packet_file.with_suffix(".json")
        if candidate.exists():
            packet_json = candidate
    patch_corpus = _load_patch_file(patch_file)
    violations.extend(check_rule_card_attestation(report, packet_json, patch_corpus))
    violations.extend(check_rule_card_coverage(report, packet_json))
    violations.extend(check_focused_review_obligations(report, packet_json))
    violations.extend(check_runtime_override_artifact(
        runtime_config=runtime_config,
        sparse_file=sparse_file,
        html_text=html,
        require_summary_row=False,
    ))
    evidence_manifest = _load_evidence_manifest(evidence_file)
    evidence_by_block = {patch_number - 1: evidence_manifest} if evidence_manifest else {}
    violations.extend(check_evidence_manifest_record(report, evidence_by_block))
    violations.extend(check_evidence_required_reads(report, evidence_by_block))

    if require_patches and not patch_corpus:
        violations.append(Violation(
            "source_corpus_required",
            f"block#{patch_number}",
            "block-mode validation requires the patch diff/corpus for this "
            "patch so source-aware checks can run before final assembly",
        ))
    violations.extend(_source_aware_violations(report, patch_corpus, source_root, evidence_by_block))

    if not violations:
        print(
            f"PASS: {block_file.name} — patch {patch_number}, "
            f"{sum(len(b.findings) for b in report.blocks)} findings"
        )
        return 0
    return _print_violations(block_file.name, violations, output_format)


# Extracts the series-id (msgid@host) from the Message-ID row in a report.
# Two formats seen in the wild:
#   <code>&lt;msgid@host&gt;</code>  (HTML-encoded angle brackets)
#   <code>msgid@host</code>           (plain, no angle brackets)
_MESSAGE_ID_SERIES_RE = re.compile(
    r"Message-ID.*?<code>(?:&lt;)?([^&<>@\s]+@[^&<>\s]+?)(?:&gt;)?</code>",
    re.IGNORECASE | re.DOTALL,
)


def run(
    html_path: Path,
    tests_path: Optional[Path],
    patches_dir: Optional[Path] = None,
    require_patches: bool = False,
    source_root: Optional[Path] = None,
    evidence_dir: Optional[Path] = None,
    runtime_config: Optional[Path] = None,
    sparse_file: Optional[Path] = None,
    output_format: str = "human",
) -> int:
    html = html_path.read_text(encoding="utf-8")
    report = parse_report(html)

    if report.verdict == "CANNOT APPLY" and not report.blocks:
        print(f"PASS: {html_path.name} — CANNOT APPLY report")
        return 0

    tests_text = _tests_text_from(tests_path, html)

    tmp_dir: Optional[Path] = None
    if tests_path is not None:
        tmp_dir = tests_path.parent
    elif (Path.cwd() / "tmp").is_dir():
        tmp_dir = Path.cwd() / "tmp"

    violations: list[Violation] = []
    violations.extend(check_banner_consistency(report))
    violations.extend(check_verdict_counts_consistency(report))
    violations.extend(check_banner_dedup(report))
    violations.extend(check_build_break_order(report, tests_text))
    violations.extend(check_build_artifact_validity(report, tmp_dir))
    violations.extend(_report_only_violations(report))
    violations.extend(check_runtime_override_artifact(
        runtime_config=runtime_config,
        sparse_file=sparse_file,
        html_text=html,
        require_summary_row=True,
    ))
    evidence_by_block = _load_evidence_dir(evidence_dir)
    violations.extend(check_evidence_manifest_record(report, evidence_by_block))
    violations.extend(check_evidence_required_reads(report, evidence_by_block))

    # Derive series_id from the Message-ID in the HTML to scope the
    # patch corpus to only this series' mbox files, avoiding cross-
    # contamination from other series in the same tmp directory.
    _mid_m = _MESSAGE_ID_SERIES_RE.search(html)
    series_id = _mid_m.group(1) if _mid_m else ""
    patch_corpus = _load_patch_corpus(patches_dir, series_id=series_id)
    if require_patches and not patch_corpus:
        violations.append(Violation(
            "source_corpus_required",
            "report (daemon validation)",
            "daemon validation requires a non-empty patch corpus so source-aware "
            "backstops cannot be silently downgraded to HTML-only validation",
        ))
    if patch_corpus:
        violations.extend(_source_aware_violations(report, patch_corpus, source_root, evidence_by_block))

    if not violations:
        print(
            f"PASS: {html_path.name} — "
            f"{len(report.blocks)} commit-blocks, "
            f"{sum(len(b.findings) for b in report.blocks)} findings, "
            f"{len(report.verdict_banner)} banner cards"
        )
        return 0

    return _print_violations(html_path.name, violations, output_format)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "html_path",
        type=Path,
        nargs="?",
        help="path to the assembled review HTML",
    )
    ap.add_argument(
        "--block-file",
        type=Path,
        default=None,
        help="single tmp/patch_N_block.html fragment to validate before final assembly",
    )
    ap.add_argument(
        "--patch-file",
        type=Path,
        default=None,
        help="single patch diff/mbox for --block-file source-aware validation",
    )
    ap.add_argument(
        "--prompt-file",
        type=Path,
        default=None,
        help="saved per-patch subagent prompt for --block-file validation",
    )
    ap.add_argument(
        "--build-file",
        type=Path,
        default=None,
        help="per-patch build log for --block-file validation",
    )
    ap.add_argument(
        "--packet-file",
        type=Path,
        default=None,
        help="per-patch compact review packet (patch_N_review_packet.md) for --block-file validation",
    )
    ap.add_argument(
        "--evidence-file",
        type=Path,
        default=None,
        help="per-patch evidence manifest for --block-file validation",
    )
    ap.add_argument(
        "--runtime-config",
        type=Path,
        default=None,
        help="daemon/runtime config artifact for this run",
    )
    ap.add_argument(
        "--sparse-file",
        type=Path,
        default=None,
        help="sparse artifact path for this run",
    )
    ap.add_argument(
        "--tests",
        type=Path,
        default=None,
        help="path to tests_<slug>.txt for build-break detection (optional)",
    )
    ap.add_argument(
        "--patches-dir",
        type=Path,
        default=None,
        help="directory containing the patch series mbox/.patch files; "
             "enables source-aware backstops for touched PM, DT, helper, "
             "and resource-abstraction checks (optional unless "
             "--require-patches is set)",
    )
    ap.add_argument(
        "--require-patches",
        action="store_true",
        help="fail if --patches-dir does not yield a non-empty patch corpus; "
             "daemon reviews should set this so validation cannot downgrade "
             "to HTML-only checks",
    )
    ap.add_argument(
        "--source-root",
        type=Path,
        default=None,
        help="post-apply source tree root; enables source-aware checks that "
             "must inspect touched files beyond patch hunk context",
    )
    ap.add_argument(
        "--evidence-dir",
        type=Path,
        default=None,
        help="directory containing patch_<N>_evidence.json manifests for "
             "assembled-report validation",
    )
    ap.add_argument(
        "--format",
        choices=("human", "json"),
        default="human",
        help="output format on failure. 'json' emits one object per violation "
             "with a per-check 'fix' and 'ref' remediation pointer so the "
             "daemon repair pass can build a scoped repair prompt; the human "
             "format also appends the fix/ref hints under each check group.",
    )
    args = ap.parse_args(argv)

    if args.block_file is not None:
        if not args.block_file.exists():
            print(f"error: {args.block_file} does not exist", file=sys.stderr)
            return 2
        return run_block(
            args.block_file,
            args.tests,
            patch_file=args.patch_file,
            prompt_file=args.prompt_file,
            build_file=args.build_file,
            evidence_file=args.evidence_file,
            require_patches=args.require_patches,
            source_root=args.source_root,
            packet_file=args.packet_file,
            runtime_config=args.runtime_config,
            sparse_file=args.sparse_file,
            output_format=args.format,
        )

    if args.html_path is None:
        print("error: html_path is required unless --block-file is used", file=sys.stderr)
        return 2
    if not args.html_path.exists():
        print(f"error: {args.html_path} does not exist", file=sys.stderr)
        return 2
    return run(
        args.html_path,
        args.tests,
        args.patches_dir,
        args.require_patches,
        args.source_root,
        args.evidence_dir,
        args.runtime_config,
        args.sparse_file,
        output_format=args.format,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
