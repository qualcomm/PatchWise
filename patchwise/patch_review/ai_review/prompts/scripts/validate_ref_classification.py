#!/usr/bin/env python3
"""Validate refs/ref-classification.json for reviewer-packet boundaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA = "review-commits.ref-classification.v1"
VALID_CLASSES = {
    "orchestrator-only",
    "reviewer-base",
    "output-format",
    "rule-card",
    "validator-only",
    "legacy-only",
}
SUBAGENT_ALLOWED_CLASSES = {"reviewer-base", "output-format", "rule-card"}


def validate(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    refs_dir = skill_dir / "refs"
    path = refs_dir / "ref-classification.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read {path}: {exc}"]
    if not isinstance(data, dict):
        return ["ref-classification root must be an object"]
    if data.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA!r}, got {data.get('schema')!r}")

    expected_refs = {
        ref.relative_to(skill_dir).as_posix()
        for ref in refs_dir.rglob("*")
        if ref.is_file()
    }
    expected_refs.add("refs/ref-classification.json")
    classified_refs = {key for key in data if key.startswith("refs/")}
    missing = sorted(expected_refs - classified_refs)
    extra = sorted(classified_refs - expected_refs)
    if missing:
        errors.append("missing classifications: " + ", ".join(missing))
    if extra:
        errors.append("classifications for missing refs: " + ", ".join(extra))

    for ref in sorted(classified_refs):
        entry: Any = data.get(ref)
        if not isinstance(entry, dict):
            errors.append(f"{ref}: classification entry must be an object")
            continue
        ref_class = entry.get("class")
        allowed = entry.get("subagent_allowed")
        if ref_class not in VALID_CLASSES:
            errors.append(f"{ref}: invalid class {ref_class!r}")
        if not isinstance(allowed, bool):
            errors.append(f"{ref}: subagent_allowed must be boolean")
        elif allowed and ref_class not in SUBAGENT_ALLOWED_CLASSES:
            errors.append(f"{ref}: class {ref_class!r} cannot be subagent_allowed")
        elif not allowed and ref_class in SUBAGENT_ALLOWED_CLASSES:
            errors.append(f"{ref}: class {ref_class!r} should be subagent_allowed")
    return errors


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate review-commits ref classification")
    parser.add_argument("--skill-dir", type=Path, default=Path(__file__).resolve().parents[1])
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    errors = validate(args.skill_dir.expanduser().resolve())
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"ref classification valid: {args.skill_dir / 'refs' / 'ref-classification.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
