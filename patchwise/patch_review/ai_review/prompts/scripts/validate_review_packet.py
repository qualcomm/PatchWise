#!/usr/bin/env python3
"""Validate compact per-patch reviewer packets."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "review-commits.reviewer-packet.v1"
REQUIRED_MARKERS = (
    "<!-- BEGIN packet-metadata -->",
    "<!-- BEGIN reviewer-base -->",
    "<!-- BEGIN output-format-mini -->",
    "<!-- BEGIN focused-review-obligations -->",
    "<!-- BEGIN focused-rule-evidence -->",
    "<!-- BEGIN context-snippets -->",
    "<!-- BEGIN context-coverage -->",
    "<!-- BEGIN selected-rule-cards -->",
    "<!-- BEGIN commit-message -->",
    "<!-- BEGIN checker-evidence -->",
    "<!-- BEGIN patch-diff -->",
)
FORBIDDEN_PATTERNS = (
    r"refs/startup-workflow\.md",
    r"refs/orchestrator-workflow\.md",
    r"refs/html-template\.md",
    r"refs/mode-c-workflow\.md",
    r"MANDATORY startup path",
    r"Subagent Mandatory Step Completion Proof",
    r"STEP_COMPLETION_RECORD",
    r"git am",
    r"b4\s+",
)
PATCH_DIFF_RE = re.compile(r"(?s)<!-- BEGIN patch-diff -->.*?<!-- END patch-diff -->")
OUTPUT_FORMAT_RE = re.compile(r"(?s)<!-- BEGIN output-format-mini -->.*?<!-- END output-format-mini -->")
CARD_RE = re.compile(r"<!-- BEGIN selected-rule-card:([^ >]+) -->")


def non_diff_text(text: str) -> str:
    return PATCH_DIFF_RE.sub("<!-- patch-diff elided for size budget -->", text)


def step_record_scan_text(text: str) -> str:
    return OUTPUT_FORMAT_RE.sub("<!-- output-format-mini allowed to document block-local step record -->", text)


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("packet JSON root must be an object")
    return data


def load_required_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: root must be an object")
    return data


def load_rule_index(skill_dir: Path) -> dict[str, str]:
    data = load_required_json(skill_dir / "refs" / "rule-index.json")
    cards = data.get("rule_cards", [])
    if not isinstance(cards, list):
        raise ValueError("refs/rule-index.json: rule_cards must be a list")
    indexed: dict[str, str] = {}
    for index, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            raise ValueError(f"refs/rule-index.json: rule_cards[{index}] must be an object")
        card_id = card.get("id")
        card_path = card.get("card")
        if not isinstance(card_id, str) or not card_id:
            raise ValueError(f"refs/rule-index.json: rule_cards[{index}].id must be non-empty")
        if not isinstance(card_path, str) or not card_path.startswith("refs/rule-cards/"):
            raise ValueError(f"refs/rule-index.json: rule card {card_id} has invalid path")
        indexed[card_id] = card_path
    return indexed


def load_ref_classification(skill_dir: Path) -> dict[str, Any]:
    data = load_required_json(skill_dir / "refs" / "ref-classification.json")
    if data.get("schema") != "review-commits.ref-classification.v1":
        raise ValueError("refs/ref-classification.json: schema mismatch")
    return data


def require_subagent_allowed(
    *,
    classification: dict[str, Any],
    ref_path: str,
    errors: list[str],
) -> None:
    entry = classification.get(ref_path)
    if not isinstance(entry, dict):
        errors.append(f"ref classification missing included ref: {ref_path}")
        return
    if entry.get("subagent_allowed") is not True:
        errors.append(f"ref is not allowed in reviewer packet: {ref_path}")


def validate_metadata(
    metadata: dict[str, Any],
    required_cards: list[str],
    errors: list[str],
    warnings: list[str],
    *,
    skill_dir: Path,
    indexed_cards: dict[str, str],
    classification: dict[str, Any],
    max_card_bytes: int,
) -> None:
    if metadata.get("schema") != SCHEMA:
        errors.append(f"packet JSON schema must be {SCHEMA!r}, got {metadata.get('schema')!r}")
    cards = metadata.get("rule_cards")
    if not isinstance(cards, list):
        errors.append("packet JSON rule_cards must be a list")
        return
    card_ids: list[str] = []
    for index, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            errors.append(f"packet JSON rule_cards[{index}] must be an object")
            continue
        card_id = card.get("id")
        card_path = card.get("card")
        triggers = card.get("triggers")
        if not isinstance(card_id, str) or not card_id:
            errors.append(f"packet JSON rule_cards[{index}].id must be non-empty")
        else:
            card_ids.append(card_id)
        if not isinstance(card_path, str) or not card_path.startswith("refs/rule-cards/"):
            errors.append(f"packet JSON rule_cards[{index}].card must be under refs/rule-cards/")
        if isinstance(card_id, str) and isinstance(card_path, str):
            indexed_path = indexed_cards.get(card_id)
            if indexed_path is None:
                errors.append(f"packet JSON rule card is not indexed: {card_id}")
            elif indexed_path != card_path:
                errors.append(f"packet JSON rule card {card_id} path mismatch: expected {indexed_path}, got {card_path}")
            require_subagent_allowed(classification=classification, ref_path=card_path, errors=errors)
            full_card_path = skill_dir / card_path
            if not full_card_path.is_file():
                errors.append(f"packet JSON rule card file missing: {card_path}")
            else:
                size = len(full_card_path.read_bytes())
                if size > max_card_bytes:
                    warnings.append(f"rule card {card_id} is {size} bytes, exceeds target {max_card_bytes}")
        if not isinstance(triggers, list) or not all(isinstance(item, str) and item for item in triggers):
            errors.append(f"packet JSON rule_cards[{index}].triggers must be non-empty strings")
    missing = sorted(set(required_cards) - set(card_ids))
    if missing:
        errors.append("packet JSON missing required cards: " + ", ".join(missing))

    matched_cards = metadata.get("matched_rule_cards")
    deferred_cards = metadata.get("deferred_rule_cards")
    budget = metadata.get("rule_card_budget")
    if matched_cards is not None:
        if not isinstance(matched_cards, list):
            errors.append("packet JSON matched_rule_cards must be a list")
        else:
            matched_ids = {
                card.get("id") for card in matched_cards
                if isinstance(card, dict) and isinstance(card.get("id"), str)
            }
            missing_active = sorted(set(card_ids) - matched_ids)
            if missing_active:
                errors.append("packet JSON active rule_cards missing from matched_rule_cards: " + ", ".join(missing_active))
    if deferred_cards is not None:
        if not isinstance(deferred_cards, list):
            errors.append("packet JSON deferred_rule_cards must be a list")
        else:
            deferred_ids = {
                card.get("id") for card in deferred_cards
                if isinstance(card, dict) and isinstance(card.get("id"), str)
            }
            overlap = sorted(set(card_ids) & deferred_ids)
            if overlap:
                errors.append("packet JSON deferred_rule_cards overlaps active rule_cards: " + ", ".join(overlap))
    if budget is not None:
        if not isinstance(budget, dict):
            errors.append("packet JSON rule_card_budget must be an object")
        else:
            for key in ("matched_count", "active_count", "deferred_count", "max_active"):
                if not isinstance(budget.get(key), int):
                    errors.append(f"packet JSON rule_card_budget.{key} must be an integer")
            if isinstance(budget.get("active_count"), int) and budget["active_count"] != len(card_ids):
                errors.append("packet JSON rule_card_budget.active_count does not match rule_cards length")




def selected_card_ids(metadata: dict[str, Any]) -> list[str]:
    cards = metadata.get("rule_cards")
    if not isinstance(cards, list):
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for card in cards:
        card_id = card.get("id") if isinstance(card, dict) else card
        if isinstance(card_id, str) and card_id and card_id not in seen:
            seen.add(card_id)
            ids.append(card_id)
    return ids


def validate_focused_obligations(metadata: dict[str, Any], text: str, errors: list[str]) -> None:
    card_ids = selected_card_ids(metadata)
    obligations = metadata.get("focused_review_obligations")
    if not card_ids:
        if obligations not in (None, []):
            errors.append(
                "packet JSON focused_review_obligations must be empty when no rule cards are selected"
            )
        return
    if not isinstance(obligations, list) or not obligations:
        errors.append(
            "packet JSON focused_review_obligations must be a non-empty list when rule cards are selected"
        )
        return

    selected = set(card_ids)
    ids: set[str] = set()
    obligations_by_card: dict[str, int] = {card_id: 0 for card_id in card_ids}
    for index, obligation in enumerate(obligations, start=1):
        if not isinstance(obligation, dict):
            errors.append(f"packet JSON focused_review_obligations[{index}] must be an object")
            continue
        obligation_id = obligation.get("id")
        card_id = obligation.get("card")
        if not isinstance(obligation_id, str) or not obligation_id:
            errors.append(f"packet JSON focused_review_obligations[{index}].id must be non-empty")
            continue
        if obligation_id in ids:
            errors.append(f"duplicate focused review obligation id: {obligation_id}")
        ids.add(obligation_id)
        if not isinstance(card_id, str) or card_id not in selected:
            errors.append(
                f"packet JSON focused_review_obligations[{index}].card must name a selected rule card"
            )
        else:
            obligations_by_card[card_id] += 1
            if not obligation_id.startswith(f"{card_id}#"):
                errors.append(
                    f"focused review obligation id {obligation_id!r} must start with {card_id}#"
                )
        for key in ("file", "trigger", "text"):
            value = obligation.get(key)
            if not isinstance(value, str) or not value:
                errors.append(
                    f"packet JSON focused_review_obligations[{index}].{key} must be non-empty"
                )
        if obligation_id and obligation_id not in text:
            errors.append(f"packet text focused-review-obligations section missing id: {obligation_id}")

    missing_cards = [card_id for card_id, count in obligations_by_card.items() if count == 0]
    if missing_cards:
        errors.append(
            "packet JSON focused_review_obligations missing selected cards: "
            + ", ".join(missing_cards)
        )
    for required_word in ("FINDING", "SAFE", "INCONCLUSIVE"):
        if required_word not in text:
            errors.append(
                "packet text focused-review-obligations section must define disposition "
                f"status {required_word}"
            )


def validate_focused_hunks(metadata: dict[str, Any], text: str, errors: list[str]) -> None:
    card_ids = selected_card_ids(metadata)
    focused = metadata.get("focused_hunks_by_rule")
    if not card_ids:
        if focused not in (None, []):
            errors.append("packet JSON focused_hunks_by_rule must be empty when no rule cards are selected")
        return
    if not isinstance(focused, list):
        errors.append("packet JSON focused_hunks_by_rule must be a list when rule cards are selected")
        return

    focused_by_card: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(focused, start=1):
        if not isinstance(item, dict):
            errors.append(f"packet JSON focused_hunks_by_rule[{index}] must be an object")
            continue
        card_id = item.get("card")
        if not isinstance(card_id, str) or not card_id:
            errors.append(f"packet JSON focused_hunks_by_rule[{index}].card must be non-empty")
            continue
        focused_by_card[card_id] = item
        hunks = item.get("hunks")
        if not isinstance(hunks, list):
            errors.append(f"packet JSON focused_hunks_by_rule[{index}].hunks must be a list")
            continue
        if item.get("missing") is True or not hunks:
            errors.append(f"selected rule card {card_id} has no focused trigger hunk in packet JSON")
            continue
        for hunk_index, hunk in enumerate(hunks, start=1):
            if not isinstance(hunk, dict):
                errors.append(
                    f"packet JSON focused_hunks_by_rule[{index}].hunks[{hunk_index}] must be an object"
                )
                continue
            for key in ("file", "header", "matched_trigger", "text"):
                value = hunk.get(key)
                if not isinstance(value, str) or not value:
                    errors.append(
                        f"packet JSON focused_hunks_by_rule[{index}].hunks[{hunk_index}].{key} must be non-empty"
                    )

    missing_cards = sorted(set(card_ids) - set(focused_by_card))
    if missing_cards:
        errors.append("packet JSON focused_hunks_by_rule missing selected cards: " + ", ".join(missing_cards))
    extra_cards = sorted(set(focused_by_card) - set(card_ids))
    if extra_cards:
        errors.append("packet JSON focused_hunks_by_rule contains unselected cards: " + ", ".join(extra_cards))
    for card_id in card_ids:
        if f"## {card_id}" not in text:
            errors.append(f"packet text focused-rule-evidence section missing selected card: {card_id}")


def validate_context_coverage(metadata: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    coverage = metadata.get("context_coverage")
    if coverage is None:
        warnings.append("packet JSON has no context_coverage inventory")
        return
    if not isinstance(coverage, list):
        errors.append("packet JSON context_coverage must be a list")
        return
    valid_statuses = {"evidence_in_packet", "missing_from_packet"}
    for card_index, card in enumerate(coverage, start=1):
        if not isinstance(card, dict):
            errors.append(f"packet JSON context_coverage[{card_index}] must be an object")
            continue
        card_id = card.get("card")
        if not isinstance(card_id, str) or not card_id:
            errors.append(f"packet JSON context_coverage[{card_index}].card must be non-empty")
        required = card.get("required")
        if not isinstance(required, list):
            errors.append(f"packet JSON context_coverage[{card_index}].required must be a list")
            continue
        for req_index, requirement in enumerate(required, start=1):
            if not isinstance(requirement, dict):
                errors.append(
                    f"packet JSON context_coverage[{card_index}].required[{req_index}] must be an object"
                )
                continue
            name = requirement.get("name")
            status = requirement.get("status")
            evidence = requirement.get("evidence")
            if not isinstance(name, str) or not name:
                errors.append(
                    f"packet JSON context_coverage[{card_index}].required[{req_index}].name must be non-empty"
                )
            if status not in valid_statuses:
                errors.append(
                    f"packet JSON context_coverage[{card_index}].required[{req_index}].status "
                    f"must be one of {sorted(valid_statuses)}"
                )
            if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
                errors.append(
                    f"packet JSON context_coverage[{card_index}].required[{req_index}].evidence must be a string list"
                )


def validate_packet(args: argparse.Namespace) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    skill_dir = args.skill_dir.expanduser().resolve()
    try:
        indexed_cards = load_rule_index(skill_dir)
        classification = load_ref_classification(skill_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"cannot load packet validation metadata: {exc}"], []
    text = args.packet.read_text(encoding="utf-8", errors="replace")
    require_subagent_allowed(classification=classification, ref_path="refs/reviewer-base.md", errors=errors)
    require_subagent_allowed(classification=classification, ref_path="refs/output-format-mini.md", errors=errors)
    for marker in REQUIRED_MARKERS:
        if marker not in text:
            errors.append(f"missing required marker: {marker}")
    compact_text = non_diff_text(text)
    for pattern in FORBIDDEN_PATTERNS:
        if pattern == r"STEP_COMPLETION_RECORD":
            scan_text = step_record_scan_text(compact_text)
        else:
            scan_text = compact_text
        if re.search(pattern, scan_text):
            errors.append(f"forbidden packet content matched: {pattern}")

    compact_size = len(compact_text.encode("utf-8"))
    if compact_size > args.max_nondiff_bytes:
        warnings.append(
            f"non-diff packet content is {compact_size} bytes, "
            f"exceeds target {args.max_nondiff_bytes}"
        )

    card_ids = CARD_RE.findall(text)
    if len(card_ids) > args.max_cards:
        warnings.append(f"selected card count {len(card_ids)} exceeds target {args.max_cards}")
    missing_text_cards = sorted(set(args.require_card) - set(card_ids))
    if missing_text_cards:
        errors.append("packet text missing required cards: " + ", ".join(missing_text_cards))

    try:
        metadata = load_json(args.json)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"invalid packet JSON: {exc}")
        metadata = None
    if metadata is not None:
        validate_metadata(
            metadata,
            args.require_card,
            errors,
            warnings,
            skill_dir=skill_dir,
            indexed_cards=indexed_cards,
            classification=classification,
            max_card_bytes=args.max_card_bytes,
        )
        metadata_card_ids = selected_card_ids(metadata)
        missing_text_cards = sorted(set(metadata_card_ids) - set(card_ids))
        if missing_text_cards:
            errors.append("packet text missing metadata-selected cards: " + ", ".join(missing_text_cards))
        extra_text_cards = sorted(set(card_ids) - set(metadata_card_ids))
        if extra_text_cards:
            errors.append("packet text contains cards absent from packet JSON: " + ", ".join(extra_text_cards))
        validate_focused_hunks(metadata, text, errors)
        validate_focused_obligations(metadata, text, errors)
        validate_context_coverage(metadata, errors, warnings)
    return errors, warnings


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a compact per-patch reviewer packet")
    parser.add_argument("packet", type=Path)
    parser.add_argument("--json", type=Path, required=True, help="Required packet JSON sidecar")
    parser.add_argument("--skill-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--max-nondiff-bytes", type=int, default=25 * 1024,
                        help="non-diff packet target size; excess is a warning, not a hard failure")
    parser.add_argument("--max-card-bytes", type=int, default=3 * 1024,
                        help="per-card target size; excess is a warning, not a hard failure")
    parser.add_argument("--max-cards", type=int, default=8,
                        help="selected-card target count; excess is a warning, not a hard failure")
    parser.add_argument("--require-card", action="append", default=[])
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    errors, warnings = validate_packet(args)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"review packet valid: {args.packet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
