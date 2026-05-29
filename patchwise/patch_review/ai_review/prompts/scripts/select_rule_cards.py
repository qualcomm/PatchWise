#!/usr/bin/env python3
"""Select compact reviewer rule cards from refs/rule-index.json.

The selector is intentionally data-driven: card metadata and trigger patterns
live in rule-index.json, while this script provides deterministic matching over
changed paths, changed diff lines, and commit message text.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from _packet_patterns import changed_diff_text

RULE_INDEX = "refs/rule-index.json"


def load_rule_cards(skill_dir: Path) -> list[dict[str, Any]]:
    path = skill_dir / RULE_INDEX
    data = json.loads(path.read_text(encoding="utf-8"))
    cards = data.get("rule_cards", [])
    if not isinstance(cards, list):
        raise ValueError(f"{RULE_INDEX}: rule_cards must be a list")
    normalized: list[dict[str, Any]] = []
    for index, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            raise ValueError(f"{RULE_INDEX}: rule_cards[{index}] must be an object")
        card_id = card.get("id")
        card_path = card.get("card")
        if not isinstance(card_id, str) or not card_id:
            raise ValueError(f"{RULE_INDEX}: rule_cards[{index}].id must be non-empty")
        if not isinstance(card_path, str) or not card_path.startswith("refs/rule-cards/"):
            raise ValueError(f"{RULE_INDEX}: rule_cards[{index}].card must be under refs/rule-cards/")
        if not (skill_dir / card_path).is_file():
            raise ValueError(f"{RULE_INDEX}: rule card file missing: {card_path}")
        normalized.append(card)
    return normalized


def string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"trigger field {field} must be a list of non-empty strings")
    return value


def any_path_prefix(paths: Iterable[str], prefixes: Iterable[str]) -> list[str]:
    matches: list[str] = []
    for prefix in prefixes:
        for path in paths:
            if path == prefix.rstrip("/") or path.startswith(prefix):
                matches.append(f"path:{prefix}")
                break
    return matches


def any_path_regex(paths: Iterable[str], patterns: Iterable[str]) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        compiled = re.compile(pattern)
        if any(compiled.search(path) for path in paths):
            matches.append(f"path-regex:{pattern}")
    return matches


def any_text_regex(text: str, patterns: Iterable[str], label: str) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        compiled = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        if compiled.search(text):
            matches.append(f"{label}:{pattern}")
    return matches


def all_text_regex(text: str, patterns: Iterable[str]) -> bool:
    return all(re.compile(pattern, re.IGNORECASE | re.MULTILINE).search(text) for pattern in patterns)


def select_rule_cards(
    *,
    skill_dir: Path,
    paths: list[str],
    diff_text: str,
    message: str,
) -> list[dict[str, Any]]:
    changed_text = changed_diff_text(diff_text)
    selected: list[dict[str, Any]] = []
    for card in load_rule_cards(skill_dir):
        triggers = card.get("triggers", {})
        if not isinstance(triggers, dict):
            raise ValueError(f"rule card {card['id']}: triggers must be an object")
        path_evidence: list[str] = []
        path_evidence.extend(any_path_prefix(paths, string_list(triggers.get("paths_any"), "paths_any")))
        path_evidence.extend(any_path_regex(paths, string_list(triggers.get("paths_regex_any"), "paths_regex_any")))
        text_evidence: list[str] = []
        text_evidence.extend(any_text_regex(changed_text, string_list(triggers.get("diff_regex_any"), "diff_regex_any"), "diff"))
        text_evidence.extend(any_text_regex(message, string_list(triggers.get("message_regex_any"), "message_regex_any"), "message"))
        evidence = [*path_evidence, *text_evidence]
        required_paths = string_list(triggers.get("require_paths_any"), "require_paths_any")
        if required_paths and not any_path_prefix(paths, required_paths):
            continue
        required_path_regex = string_list(triggers.get("require_paths_regex_any"), "require_paths_regex_any")
        if required_path_regex and not any_path_regex(paths, required_path_regex):
            continue
        required_diff = string_list(triggers.get("require_diff_regex_any"), "require_diff_regex_any")
        if required_diff and not any_text_regex(changed_text, required_diff, "diff"):
            continue
        required_diff_all = string_list(triggers.get("require_diff_regex_all"), "require_diff_regex_all")
        if required_diff_all and not all_text_regex(changed_text, required_diff_all):
            continue
        required_message = string_list(triggers.get("require_message_regex_any"), "require_message_regex_any")
        if required_message and not any_text_regex(message, required_message, "message"):
            continue
        path_only = triggers.get("path_only", False)
        if not isinstance(path_only, bool):
            raise ValueError(f"rule card {card['id']}: triggers.path_only must be boolean")
        if text_evidence or (path_only and path_evidence):
            selected.append({
                "id": card["id"],
                "card": card["card"],
                "triggers": evidence,
                "requires_context": card.get("requires_context", []),
            })
    return selected


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select reviewer rule cards from rule-index.json")
    parser.add_argument("--skill-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--paths", action="append", default=[], help="Changed file path; repeatable")
    parser.add_argument("--paths-file", type=Path, help="File containing changed paths, one per line")
    parser.add_argument("--diff-file", type=Path, help="Patch diff file")
    parser.add_argument("--message-file", type=Path, help="Commit message file")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    paths = list(args.paths)
    if args.paths_file:
        paths.extend(line.strip() for line in args.paths_file.read_text(encoding="utf-8").splitlines() if line.strip())
    diff_text = args.diff_file.read_text(encoding="utf-8", errors="replace") if args.diff_file else ""
    message = args.message_file.read_text(encoding="utf-8", errors="replace") if args.message_file else ""
    try:
        cards = select_rule_cards(
            skill_dir=args.skill_dir.expanduser().resolve(),
            paths=paths,
            diff_text=diff_text,
            message=message,
        )
    except (OSError, ValueError, json.JSONDecodeError, re.error) as exc:
        print(f"select_rule_cards.py: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(cards, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
