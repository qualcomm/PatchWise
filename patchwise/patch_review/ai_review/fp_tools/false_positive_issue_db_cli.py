# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from patchwise.patch_review.ai_review.fp_tools.false_positive_issue_db import (
    FalsePositiveDB,
    VECTOR_DB_PATH,
    _FP_DB_DEFAULT_TOP_K,
    _FP_DB_SIMILARITY_THRESHOLD,
)

logger = logging.getLogger(__name__)


def _initialize_false_positive_db(path: Path) -> FalsePositiveDB | None:
    db = FalsePositiveDB(db_path=path)
    db.initialize()
    if not db.is_available():
        logger.error("FalsePositiveDB not available — check ai.fp_tools config.")
        return None
    return db


def _load_false_positive_issue_records(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        records = json.loads(text)
        if not isinstance(records, list):
            raise ValueError("JSON input must be an array of objects")
        return records
    records = []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            logger.warning("Skipping line %d: %s", lineno, exc)
    return records


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Manage the FalsePositiveDB — populate, search, clear, count.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")

    pop = sub.add_parser("populate", help="Append FP records from a JSON/JSONL file into the DB.")
    pop.add_argument("input", type=Path, help="JSON array or JSONL file with FP records.")
    pop.add_argument("--db", type=Path, default=VECTOR_DB_PATH)

    srch = sub.add_parser("search", help="Search FalsePositiveDB semantically.")
    srch.add_argument("--issue", required=True, help="Issue description to search for.")
    srch.add_argument("--code", default="", help="Code snippet (optional).")
    srch.add_argument("--db", type=Path, default=VECTOR_DB_PATH)
    srch.add_argument("--n", type=int, default=_FP_DB_DEFAULT_TOP_K)
    srch.add_argument("--threshold", type=float, default=_FP_DB_SIMILARITY_THRESHOLD)

    clr = sub.add_parser("clear", help="Delete all entries from FalsePositiveDB.")
    clr.add_argument("--db", type=Path, default=VECTOR_DB_PATH)

    cnt = sub.add_parser("count", help="Print number of stored findings.")
    cnt.add_argument("--db", type=Path, default=VECTOR_DB_PATH)

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return

    if args.cmd == "populate":
        if not args.input.exists():
            logger.error("Input file not found: %s", args.input)
            return
        try:
            records = _load_false_positive_issue_records(args.input)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.error("Failed to load %s: %s", args.input, exc)
            return
        if not records:
            logger.error("No records found in %s", args.input)
            return
        db = _initialize_false_positive_db(args.db)
        if db is None:
            return
        stored = skipped = 0
        for r in records:
            try:
                if db.add_false_positive_issue(
                    patch_title=r["patch_title"],
                    code_snippet=r.get("code_snippet", ""),
                    issue_description=r["issue_description"],
                    reason=r["reason"],
                    issue_label=r.get("issue_label", ""),
                    message_id=r.get("message_id", ""),
                ):
                    stored += 1
            except ValueError as exc:
                logger.warning("Skipping %r: %s", r.get("patch_title", "?"), exc)
                skipped += 1
        logger.info("Populate complete: %d added, %d skipped. DB total: %d",
                    stored, skipped, db.get_count())

    elif args.cmd == "search":
        if args.n <= 0:
            logger.error("--n must be greater than 0")
            return
        db = _initialize_false_positive_db(args.db)
        if db is None:
            return
        results = db.search_similar_issues(
            code_snippet=args.code, issue_text=args.issue,
            top_k=args.n, threshold=args.threshold,
        )
        if not results:
            print("No matches found above threshold.")
            return
        for i, r in enumerate(results, 1):
            print(f"\nMatch {i} (distance={r['distance']}):")
            print(f"  patch_title       : {r['patch_title']}")
            print(f"  issue_label       : {r['issue_label']}")
            print(f"  issue_description : {r['issue_description']}")
            print(f"  code_snippet      : {r['code_snippet'] or '(none)'}")
            print(f"  reason            : {r['reason']}")

    elif args.cmd == "clear":
        db = _initialize_false_positive_db(args.db)
        if db is None:
            return
        db.clear()
        logger.info("FalsePositiveDB cleared.")

    elif args.cmd == "count":
        db = _initialize_false_positive_db(args.db)
        if db is None:
            return
        print(f"FalsePositiveDB entries: {db.get_count()}")


if __name__ == "__main__":
    main()
