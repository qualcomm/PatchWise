#!/usr/bin/env python3
"""Assemble a compact per-patch reviewer packet.

This is the packet-only per-patch reviewer artifact for Mode A/B reviews.  It
loads only the minimal reviewer contract, output contract, selected rule cards,
and patch-local evidence recorded in the series manifest.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from _packet_patterns import changed_diff_text

SCHEMA = "review-commits.reviewer-packet.v1"
MAX_CONTEXT_EVIDENCE_PER_REQUIREMENT = 3
MAX_ACTIVE_RULE_CARDS = 8
MAX_FOCUSED_HUNKS_PER_CARD = 8
FOCUSED_HUNK_RADIUS = 8
MAX_FOCUSED_HUNKS_PER_TRIGGER = 2
FOCUSED_PATH_TRIGGER_MAX_LINES = 80

HIGH_SIGNAL_RULE_CARDS = {
    "dt-binding-example-completeness",
    "dt-binding-schema-basics",
    "dt-compatible-fallback-contract",
    "dt-driver-of-match-contract",
    "dt-driver-property-read-contract",
    "dt-resource-abi-matrix",
    "dt-schema-conditional-composition",
    "firmware-xfer-buffer-contract",
    "framework-status-callback-power-state",
    "platform-child-device-resource-lifecycle",
    "qcom-scm-vmid-memory-assignment",
    "resource-acquire-release-symmetry",
}

SPECIFIC_API_TRIGGER_RE = re.compile(
    r"devm_|snd_soc_component_|qcom_scm|xfer_|do_xfer|devfreq|PLATFORM_DEVID|"
    r"request_threaded_irq|IRQF_|dma_|regmap_(?:init|exit)|FIELD_(?:PREP|GET)|"
    r"SOC_(?:SINGLE|DOUBLE|ENUM|VALUE|BYTES)|of_device_id|device_property_read|"
    r"of_property_read|MODULE_DEVICE_TABLE|compatible",
    re.IGNORECASE,
)

CONTEXT_PATTERN_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("allocation", "alloc"), (
        r"\b(?:devm_)?k(?:zalloc|malloc|calloc)\s*\(",
        r"\bdma_alloc\w*\s*\(",
        r"\b\w+_(?:alloc|create|init)\w*\s*\(",
    )),
    (("assign", "unassign", "vmid", "scm", "firmware", "secure"), (
        r"\bqcom_scm_assign_mem\b",
        r"\bQCOM_SCM_VMID_\w+\b",
        r"\bVMID\b",
        r"\bassign\w*\s*\(",
        r"\bunassign\w*\s*\(",
    )),
    (("free", "cleanup", "remove", "unprepare", "unwind", "teardown", "destroy", "unregister", "release"), (
        r"\b(?:kfree|devm_kfree|free|cleanup|remove|unprepare|destroy|unregister|release)\w*\s*\(",
        r"\bgoto\s+(?:err|fail|free|cleanup|unwind)\w*",
        r"\berr(?:or)?[_a-z0-9]*\s*:",
    )),
    (("state", "mode", "entrypoint", "alternate", "reset", "guard"), (
        r"->(?:state|mode|type|sel|src|source|cfg|config|format|route|enabled|prepared|assigned)\b",
        r"\b(?:start|stop|stream|enable|disable|reset|prepare|unprepare|trigger|open|close|probe|remove)\w*\s*\(",
        r"\b(?:TPG|tpg|test_pattern|loopback|internal|bypass|offline|mmap|copy|compress|PCM)\b",
    )),
    (("binding", "schema", "property", "compatible", "resource", "example", "provider", "cells", "dts", "dtsi", "dtb"), (
        r"\bcompatible\b",
        r"#[a-z0-9,-]+-cells\b",
        r"\b(?:reg|reg-names|interrupts|interrupt-names|clocks|clock-names|resets|reset-names|dmas|dma-names|power-domains|iommus|interconnects|interconnect-names|[a-z0-9-]+-supply)\b",
        r"<&[A-Za-z0-9_]+",
        r"\b(?:required|properties|patternProperties|additionalProperties|unevaluatedProperties|oneOf|anyOf|allOf|items|contains|examples)\s*:",
    )),
    (("driver", "parser", "getter", "lookup", "match", "xlate", "registration"), (
        r"\b(?:of_property|device_property|fwnode_property)_read_\w+\s*\(",
        r"\b(?:of_property_count|device_property_count|fwnode_property_count)_\w+\s*\(",
        r"\b(?:of_parse_phandle|of_find_|of_get_|platform_get_irq|devm_platform_ioremap|devm_clk|clk_bulk|devm_reset|devm_regulator|devm_gpiod|dma_request)\w*\s*\(",
        r"\b(?:of_device_id|of_match_table|MODULE_DEVICE_TABLE|device_get_match_data|of_device_get_match_data)\b",
    )),
    (("old_dtb", "fallback", "optional", "legacy", "breakage"), (
        r"\b(?:of_property_present|device_property_present|fwnode_property_present)\s*\(",
        r"\b(?:of_property_read|device_property_read|fwnode_property_read)_\w+\s*\(",
        r"\b(?:optional|fallback|legacy|default|missing|required)\b",
    )),
    (("pm", "runtime", "register"), (
        r"\bpm_runtime_(?:get_sync|resume_and_get|put(?:_noidle|_sync|_autosuspend)?)\s*\(",
        r"\b(?:readl|readw|readb|writel|writew|writeb|regmap_(?:read|write|update_bits))\s*\(",
        r"\bruntime_(?:suspend|resume)\w*\s*\(",
    )),
    (("irq", "interrupt", "reenable", "source", "mask"), (
        r"\b(?:request_threaded_irq|request_irq|enable_irq|disable_irq|irqreturn_t)\b",
        r"\bIRQ_TYPE_LEVEL_(?:HIGH|LOW)\b",
        r"\bIRQF_(?:TRIGGER_(?:HIGH|LOW)|ONESHOT)\b",
        r"\b(?:clear|ack|mask|unmask|status|pending)\w*\s*\(",
    )),
    (("pointer", "lifetime", "unbind", "lock", "dereference", "free", "reader", "writer"), (
        r"\b(?:mutex_lock|mutex_unlock|spin_lock|spin_unlock|guard\(|scoped_guard|get_device|put_device|kref_|refcount_)\b",
        r"\b(?:dev_get_drvdata|platform_get_drvdata|i2c_get_clientdata|spi_get_drvdata)\s*\(",
        r"\b(?:remove|unbind|detach|disconnect|hotplug|cancel_work_sync|del_timer_sync)\w*\s*\(",
        r"->\w+->\w+",
    )),
    (("arithmetic", "calculation", "aggregate", "element", "count", "width", "bounds", "range"), (
        r"\b(?:GENMASK|BIT|FIELD_PREP|FIELD_GET)\s*\(",
        r"(?<!/)\s/[=\s]*\s*[A-Za-z_][A-Za-z0-9_>.\-]*",
        r"[<>]{2}\s*[A-Za-z_][A-Za-z0-9_>.\-]*",
        r"\b(?:count|num|nr|width|bits|lanes|ports|channels|rate|size|len|cells|div|bandwidth|bw|icc|interconnect)\b",
    )),
    (("branch", "order", "side_effect", "trace"), (
        r"\b(?:if|else\s+if)\s*\(",
        r"\|\|",
        r"\b(?:init|enable|power|phy|clk|reset|setup|config|state|lock|prepare|start)\w*\s*\(",
    )),
    (("platform", "child", "device", "module", "alias", "id_table"), (
        r"\bplatform_device_(?:register_full|register_data|register_simple|unregister)\s*\(",
        r"\bstruct\s+platform_device_id\b",
        r"\.id_table\s*=",
        r"\bMODULE_DEVICE_TABLE\s*\(\s*platform\b",
        r"\birq_(?:create_fwspec_mapping|dispose_mapping)\s*\(",
    )),
)

NOISY_SEARCH_TERMS = {
    "additionalProperties",
    "allOf",
    "anyOf",
    "clock-names",
    "clocks",
    "compatible",
    "description",
    "dma-names",
    "dmas",
    "false",
    "interrupt-names",
    "interrupts",
    "items",
    "maxItems",
    "minItems",
    "oneOf",
    "properties",
    "reg",
    "required",
    "resets",
    "status",
    "true",
    "unevaluatedProperties",
}


def run_git(project: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(project),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.rstrip("\n")


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest root must be a JSON object")
    return data


def select_patch(manifest: dict[str, Any], patch_number: int) -> dict[str, Any]:
    patches = manifest.get("patches")
    if not isinstance(patches, list):
        raise ValueError("manifest patches must be a list")
    for patch in patches:
        if isinstance(patch, dict) and patch.get("n") == patch_number:
            return patch
    raise ValueError(f"patch {patch_number} not found in manifest")


def resolve_artifact(project: Path | None, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        return candidate
    if project is not None:
        project_candidate = project / candidate
        if project_candidate.exists():
            return project_candidate
    return candidate


def read_artifact(project: Path | None, relative_path: str) -> str | None:
    path = resolve_artifact(project, relative_path)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace").rstrip("\n")


def commit_message(project: Path | None, patch: dict[str, Any]) -> str:
    commit = patch.get("hash")
    if project is not None and isinstance(commit, str) and commit:
        try:
            return run_git(project, ["log", "--format=%B", "-1", commit])
        except subprocess.CalledProcessError:
            pass
    subject = patch.get("subject")
    return str(subject or "")


def patch_diff(project: Path | None, patch: dict[str, Any]) -> str:
    paths = patch.get("paths")
    diff_path = paths.get("diff") if isinstance(paths, dict) else None
    if isinstance(diff_path, str) and diff_path:
        diff_text = read_artifact(project, diff_path)
        if diff_text is not None:
            return diff_text
    commit = patch.get("hash")
    if project is not None and isinstance(commit, str) and commit:
        try:
            return run_git(project, ["show", "--format=", "--find-renames", commit])
        except subprocess.CalledProcessError:
            pass
    return "[diff unavailable: orchestrator did not provide diff artifact]"


def load_ref(skill_dir: Path, relative_path: str) -> str:
    path = skill_dir / relative_path
    if not path.exists():
        raise ValueError(f"required packet ref missing: {relative_path}")
    return path.read_text(encoding="utf-8").rstrip("\n")


def load_rule_index_cards(skill_dir: Path) -> dict[str, dict[str, Any]]:
    path = skill_dir / "refs" / "rule-index.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    cards = data.get("rule_cards", [])
    if not isinstance(cards, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for card in cards:
        if isinstance(card, dict) and isinstance(card.get("id"), str):
            indexed[card["id"]] = card
    return indexed


def indexed_trigger_strings(index_card: dict[str, Any]) -> list[str]:
    triggers = index_card.get("triggers", {})
    if not isinstance(triggers, dict):
        return []
    result: list[str] = []
    for key in ("paths_any", "require_paths_any"):
        values = triggers.get(key, [])
        if isinstance(values, list):
            result.extend(f"path:{value}" for value in values if isinstance(value, str))
    for key in ("paths_regex_any", "require_paths_regex_any"):
        values = triggers.get(key, [])
        if isinstance(values, list):
            result.extend(f"path-regex:{value}" for value in values if isinstance(value, str))
    for key in ("diff_regex_any", "require_diff_regex_any", "require_diff_regex_all"):
        values = triggers.get(key, [])
        if isinstance(values, list):
            result.extend(f"diff:{value}" for value in values if isinstance(value, str))
    return list(dict.fromkeys(result))


def expand_rule_card_triggers(
    cards: list[dict[str, Any]],
    indexed_cards: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for card in cards:
        card_id = card.get("id")
        merged = dict(card)
        existing = merged.get("triggers", [])
        existing_triggers = [item for item in existing if isinstance(item, str)] if isinstance(existing, list) else []
        merged["selection_triggers"] = existing_triggers
        index_card = indexed_cards.get(card_id) if isinstance(card_id, str) else None
        if index_card is not None:
            merged["triggers"] = list(dict.fromkeys([*existing_triggers, *indexed_trigger_strings(index_card)]))
            if "category" in index_card:
                merged["category"] = index_card["category"]
            # Propagate trigger_obligations from the rule-index entry so that
            # obligation_lines_for_trigger() can produce data-driven, card-specific
            # obligation text instead of the generic fallback.
            if "trigger_obligations" in index_card:
                merged["trigger_obligations"] = index_card["trigger_obligations"]
        else:
            merged["triggers"] = existing_triggers
        expanded.append(merged)
    return expanded


def _trigger_obligation_match(card: dict[str, Any], trigger_text: str) -> bool:
    trigger_text_l = trigger_text.lower()
    trigger_obligations = card.get("trigger_obligations", [])
    if not isinstance(trigger_obligations, list):
        return False
    for obligation in trigger_obligations:
        if not isinstance(obligation, dict):
            continue
        pattern = obligation.get("trigger_pattern")
        if isinstance(pattern, str) and pattern and pattern.lower() in trigger_text_l:
            return True
    return False


def _selection_trigger_text(card: dict[str, Any]) -> str:
    triggers = card.get("selection_triggers")
    if not isinstance(triggers, list):
        triggers = card.get("triggers", [])
    return "\n".join(item for item in triggers if isinstance(item, str))


def rule_card_priority(card: dict[str, Any], patch: dict[str, Any], index: int) -> tuple[int, int]:
    """Return deterministic post-selection priority without changing triggers."""
    card_id = card.get("id") if isinstance(card.get("id"), str) else ""
    category = card.get("category") if isinstance(card.get("category"), str) else ""
    trigger_text = _selection_trigger_text(card)
    score = 0

    if _trigger_obligation_match(card, trigger_text):
        score += 120
    if card_id in HIGH_SIGNAL_RULE_CARDS:
        score += 80
    if card.get("trigger_obligations"):
        score += 35
    if SPECIFIC_API_TRIGGER_RE.search(trigger_text):
        score += 45
    if patch.get("dt") or patch.get("dt_file") or patch.get("dt_driver"):
        if category.startswith("dt-") or card_id.startswith("dt-"):
            score += 55
    if patch.get("hardware"):
        if category.startswith(("driver-", "hardware")) or any(token in card_id for token in ("resource", "irq", "pm", "lifetime")):
            score += 25

    trigger_lines = [line for line in trigger_text.splitlines() if line]
    if trigger_lines and all(line.startswith(("path:", "path-regex:")) for line in trigger_lines):
        score -= 35
    return score, -index


def active_rule_cards(
    cards: list[dict[str, Any]],
    patch: dict[str, Any],
    *,
    max_cards: int = MAX_ACTIVE_RULE_CARDS,
) -> list[dict[str, Any]]:
    if max_cards <= 0 or len(cards) <= max_cards:
        return cards
    ranked = sorted(
        enumerate(cards),
        key=lambda item: rule_card_priority(item[1], patch, item[0]),
        reverse=True,
    )
    selected_indexes = {index for index, _card in ranked[:max_cards]}
    return [card for index, card in enumerate(cards) if index in selected_indexes]


def deferred_rule_cards(matched: list[dict[str, Any]], active: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active_ids = {card.get("id") for card in active if isinstance(card.get("id"), str)}
    return [card for card in matched if card.get("id") not in active_ids]


def section(name: str, text: str) -> str:
    return f"<!-- BEGIN {name} -->\n{text.rstrip()}\n<!-- END {name} -->\n"


def added_lines_by_file(diff_text: str) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    current_file: str | None = None
    new_line: int | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[len("+++ b/"):]
            result.setdefault(current_file, [])
            new_line = None
            continue
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            new_line = int(match.group(1)) if match else None
            continue
        if current_file is None or new_line is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            result.setdefault(current_file, []).append(new_line)
            new_line += 1
        elif line.startswith(" "):
            new_line += 1
        elif line.startswith("-"):
            continue
    return result


def merge_windows(windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not windows:
        return []
    merged: list[tuple[int, int]] = []
    for start, end in sorted(windows):
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def snippet_ref(metadata: dict[str, Any]) -> str:
    return f"{metadata['file']}:{metadata['start']}-{metadata['end']}"


def compile_context_patterns(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE | re.MULTILINE))
        except re.error:
            continue
    return compiled


def unique_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def trigger_regexes(card: dict[str, Any]) -> list[str]:
    patterns: list[str] = []
    triggers = card.get("triggers", [])
    if not isinstance(triggers, list):
        return patterns
    for trigger in triggers:
        if not isinstance(trigger, str):
            continue
        if trigger.startswith(("diff:", "message:")):
            pattern = trigger.split(":", 1)[1]
            if len(pattern) <= 120:
                patterns.append(pattern)
    return patterns


def diff_trigger_regexes(card: dict[str, Any]) -> list[str]:
    return [pattern for pattern in trigger_regexes(card) if pattern]


def path_trigger_prefixes(card: dict[str, Any]) -> list[str]:
    prefixes: list[str] = []
    triggers = card.get("triggers", [])
    if not isinstance(triggers, list):
        return prefixes
    for trigger in triggers:
        if isinstance(trigger, str) and trigger.startswith("path:"):
            prefixes.append(trigger.split(":", 1)[1])
    return prefixes


def path_regex_triggers(card: dict[str, Any]) -> list[str]:
    patterns: list[str] = []
    triggers = card.get("triggers", [])
    if not isinstance(triggers, list):
        return patterns
    for trigger in triggers:
        if isinstance(trigger, str) and trigger.startswith("path-regex:"):
            patterns.append(trigger.split(":", 1)[1])
    return patterns


def diff_hunks(diff_text: str) -> list[dict[str, Any]]:
    hunks: list[dict[str, Any]] = []
    current_file = ""
    current_header = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        if current_header or current_lines:
            hunks.append({
                "file": current_file,
                "header": current_header,
                "text": "\n".join(current_lines),
                "changed_text": changed_diff_text("\n".join(current_lines)),
            })
        current_lines = []

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            flush()
            current_file = ""
            current_header = ""
            continue
        if line.startswith("+++ b/"):
            current_file = line[len("+++ b/"):]
            continue
        if line.startswith("@@"):
            flush()
            current_header = line
            current_lines = [line]
            continue
        if current_header:
            current_lines.append(line)
    flush()
    return hunks


def file_matches_card(file_path: str, card: dict[str, Any]) -> bool:
    for prefix in path_trigger_prefixes(card):
        if file_path == prefix.rstrip("/") or file_path.startswith(prefix):
            return True
    for pattern in path_regex_triggers(card):
        try:
            if re.search(pattern, file_path):
                return True
        except re.error:
            continue
    return False


def excerpt_window(lines: list[str], line_index: int, radius: int) -> str:
    start = max(0, line_index - radius)
    end = min(len(lines), line_index + radius + 1)
    prefix = ["... focused hunk excerpt ..."] if start > 0 else []
    suffix = ["... focused hunk excerpt ..."] if end < len(lines) else []
    return "\n".join([*prefix, *lines[start:end], *suffix])


def focused_hunks_by_rule(diff_text: str, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hunks = diff_hunks(diff_text)
    focused: list[dict[str, Any]] = []
    for card in cards:
        card_id = card.get("id")
        if not isinstance(card_id, str) or not card_id:
            continue
        regexes = compile_context_patterns(diff_trigger_regexes(card))
        matches: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()

        # Walk trigger patterns before hunks so a large new file cannot consume
        # the whole budget before later files/descriptors are considered.
        for pattern in regexes:
            pattern_matches = 0
            for hunk in hunks:
                hunk_text = str(hunk.get("text", ""))
                file_path = str(hunk.get("file", ""))
                lines = hunk_text.splitlines()
                for line_index, line in enumerate(lines):
                    if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
                        continue
                    payload = line[1:] if line[:1] in {"+", "-"} else line
                    if not (pattern.search(line) or pattern.search(payload)):
                        continue
                    excerpt = excerpt_window(lines, line_index, FOCUSED_HUNK_RADIUS)
                    key = (file_path, pattern.pattern, excerpt)
                    if key in seen:
                        continue
                    seen.add(key)
                    matches.append({
                        "file": file_path,
                        "header": hunk.get("header", ""),
                        "matched_trigger": pattern.pattern,
                        "text": excerpt,
                    })
                    pattern_matches += 1
                    if (
                        len(matches) >= MAX_FOCUSED_HUNKS_PER_CARD
                        or pattern_matches >= MAX_FOCUSED_HUNKS_PER_TRIGGER
                    ):
                        break
                if (
                    len(matches) >= MAX_FOCUSED_HUNKS_PER_CARD
                    or pattern_matches >= MAX_FOCUSED_HUNKS_PER_TRIGGER
                ):
                    break
            if len(matches) >= MAX_FOCUSED_HUNKS_PER_CARD:
                break

        if not matches:
            for hunk in hunks:
                file_path = str(hunk.get("file", ""))
                if not file_matches_card(file_path, card):
                    continue
                lines = str(hunk.get("text", "")).splitlines()
                excerpt = "\n".join(lines[:FOCUSED_PATH_TRIGGER_MAX_LINES])
                matches.append({
                    "file": file_path,
                    "header": hunk.get("header", ""),
                    "matched_trigger": "path-trigger",
                    "text": excerpt,
                })
                break

        focused.append({
            "card": card_id,
            "card_entry": card,
            "hunks": matches,
            "missing": not matches,
        })
    return focused


def obligation_lines_for_trigger(
    card_id: str, trigger: str, hunk_text: str, card_entry: dict[str, Any]
) -> list[str]:
    """Return explicit review obligations for focused triggers.

    Obligations are data-driven: each rule-index card entry may carry a
    ``trigger_obligations`` list that maps trigger-pattern substrings to
    specific Must-Check questions the subagent must answer for the matched
    hunk.  Cards without ``trigger_obligations`` fall back to a generic
    "explain why SAFE / FINDING / INCONCLUSIVE" prompt.

    Adding obligations to a new card requires only a data change in
    rule-index.json — no code edit here.
    """
    obligations: list[str] = []
    trigger_l = trigger.lower()
    hunk_l = hunk_text.lower()

    # Data-driven obligations from rule-index.json
    trigger_obs = card_entry.get("trigger_obligations", [])
    for tob in trigger_obs:
        pattern = tob.get("trigger_pattern", "")
        if not pattern:
            continue
        pattern_l = pattern.lower()
        if pattern_l in trigger_l or pattern_l in hunk_l:
            text = tob.get("obligation_text", "")
            if text:
                obligations.append(text)

    if not obligations:
        obligations.append(
            f"Apply the selected `{card_id}` rule-card contract to this matched trigger: "
            "inspect the focused hunk and required context, then disposition it as SAFE, "
            "FINDING, or INCONCLUSIVE using packet evidence. A bare `checked` or generic "
            "PASS does not clear this focused trigger."
        )
    return obligations


def focused_review_obligations_section(focused: list[dict[str, Any]]) -> str:
    obligations = focused_review_obligations(focused)
    if not focused:
        return "No selected rule cards; no focused review obligations."
    parts = [
        "Every selected rule card below was triggered by focused diff evidence.",
        "For each obligation ID, the patch block must record a disposition in Rule Card Coverage or notes:",
        "- FINDING: emit a counted finding-card for the issue.",
        "- SAFE: cite the concrete packet evidence and safe-dismissal reason.",
        "- INCONCLUSIVE: name the missing evidence; do not write `No issues found` for that card.",
        "A selected card is not `checked` until every obligation ID for that card is SAFE or FINDING.",
    ]
    obligations_by_card: dict[str, list[dict[str, str]]] = {}
    for obligation in obligations:
        obligations_by_card.setdefault(obligation["card"], []).append(obligation)
    for item in focused:
        card_id = item.get("card")
        if not isinstance(card_id, str):
            continue
        parts.append(f"\n## {card_id}")
        card_obligations = obligations_by_card.get(card_id, [])
        if not card_obligations:
            parts.append("- INCONCLUSIVE obligation: no focused hunk was generated for this selected card.")
            continue
        for obligation in card_obligations:
            parts.append(
                f"{obligation['id']}. `{obligation['file']}` trigger "
                f"`{obligation['trigger']}` — {obligation['text']}"
            )
    return "\n".join(parts)


def focused_review_obligations(focused: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return stable per-trigger obligations for packet text and JSON.

    The IDs give the subagent and validators an exact handle.  Without IDs, a
    block can claim a card was checked while skipping the specific trigger that
    caused rule selection.
    """
    obligations: list[dict[str, str]] = []
    per_card_counts: dict[str, int] = {}
    seen: set[tuple[str, str, str]] = set()
    for item in focused:
        card_id = item.get("card")
        card_entry = item.get("card_entry", {})
        if not isinstance(card_id, str) or not card_id:
            continue
        hunks = item.get("hunks", [])
        if not isinstance(hunks, list) or not hunks:
            per_card_counts[card_id] = per_card_counts.get(card_id, 0) + 1
            obligations.append({
                "id": f"{card_id}#{per_card_counts[card_id]}",
                "card": card_id,
                "file": "<missing-focused-hunk>",
                "trigger": "missing-focused-hunk",
                "text": "INCONCLUSIVE obligation: no focused hunk was generated for this selected card.",
            })
            continue
        for hunk in hunks:
            if not isinstance(hunk, dict):
                continue
            file_path = str(hunk.get("file", ""))
            trigger = str(hunk.get("matched_trigger", ""))
            hunk_text = str(hunk.get("text", ""))
            for line in obligation_lines_for_trigger(card_id, trigger, hunk_text, card_entry):
                key = (card_id, file_path, line)
                if key in seen:
                    continue
                seen.add(key)
                per_card_counts[card_id] = per_card_counts.get(card_id, 0) + 1
                obligations.append({
                    "id": f"{card_id}#{per_card_counts[card_id]}",
                    "card": card_id,
                    "file": file_path,
                    "trigger": trigger,
                    "text": line,
                })
    return obligations


def focused_hunks_section(focused: list[dict[str, Any]]) -> str:
    if not focused:
        return "No selected rule cards; no focused rule evidence."
    parts = [
        "These hunks are selected by rule-card trigger evidence. Review them before broad context.",
        "If a selected card has no focused hunk, mark that card inconclusive unless other packet evidence proves it.",
    ]
    for item in focused:
        card_id = item.get("card")
        if not isinstance(card_id, str):
            continue
        parts.append(f"\n## {card_id}")
        hunks = item.get("hunks", [])
        if not isinstance(hunks, list) or not hunks:
            parts.append("No focused hunk found for this selected card.")
            continue
        for hunk in hunks:
            if not isinstance(hunk, dict):
                continue
            file_path = hunk.get("file", "")
            header = hunk.get("header", "")
            trigger = hunk.get("matched_trigger", "")
            text = hunk.get("text", "")
            parts.append(
                f"### {file_path} {header}\n"
                f"Matched trigger: `{trigger}`\n\n"
                f"```diff\n{text}\n```"
            )
    return "\n\n".join(parts)


def context_patterns(requirement: str, card: dict[str, Any]) -> list[str]:
    normalized = requirement.replace("_", " ").lower()
    patterns: list[str] = []
    for keywords, group_patterns in CONTEXT_PATTERN_GROUPS:
        if any(keyword in normalized for keyword in keywords):
            patterns.extend(group_patterns)
    if not patterns:
        patterns.extend(trigger_regexes(card))
    if not patterns:
        tokens = [token for token in re.split(r"[^a-zA-Z0-9_]+", requirement) if len(token) >= 4]
        patterns.extend(rf"\b{re.escape(token)}\b" for token in tokens)
    return unique_strings(patterns)


def extract_search_terms(diff_text: str, cards: list[dict[str, Any]]) -> list[str]:
    changed = changed_diff_text(diff_text)
    candidates: list[str] = []
    candidates.extend(re.findall(r'"([a-z0-9][a-z0-9._+-]*,[a-z0-9][a-z0-9._+-]*)"', changed, re.I))
    candidates.extend(re.findall(r"\b[a-z0-9]+,[a-z0-9][a-z0-9._+-]*\b", changed, re.I))
    candidates.extend(re.findall(r"\b[a-z0-9]+-[a-z0-9][a-z0-9-]*\b", changed, re.I))
    candidates.extend(re.findall(r"\b(?:qcom_scm_assign_mem|QCOM_SCM_VMID_\w+|pm_runtime_\w+|device_link_\w+|platform_device_\w+|of_property_read_\w+|device_property_read_\w+|fwnode_property_read_\w+|MODULE_DEVICE_TABLE)\b", changed))
    for card in cards:
        for pattern in trigger_regexes(card):
            candidates.extend(re.findall(r"[A-Za-z_][A-Za-z0-9_]{5,}", pattern))
            candidates.extend(re.findall(r"[a-z0-9]+,[a-z0-9][a-z0-9._+-]*", pattern, re.I))
    filtered = []
    for candidate in candidates:
        value = candidate.strip("'\"`")
        if len(value) < 5 or value in NOISY_SEARCH_TERMS:
            continue
        if value.lower() in {item.lower() for item in NOISY_SEARCH_TERMS}:
            continue
        filtered.append(value)
    return sorted(unique_strings(filtered), key=lambda item: ("," not in item and "qcom" not in item.lower(), len(item)))[:8]


def should_repo_search(requirement: str) -> bool:
    normalized = requirement.replace("_", " ").lower()
    return any(
        keyword in normalized
        for keyword in (
            "binding",
            "compatible",
            "consumer",
            "driver",
            "dts",
            "firmware",
            "getter",
            "match",
            "parser",
            "provider",
            "scm",
            "xlate",
        )
    )


def git_grep_matches(project: Path, terms: list[str], limit: int) -> list[tuple[str, int, str]]:
    matches: list[tuple[str, int, str]] = []
    for term in terms:
        if len(matches) >= limit:
            break
        try:
            output = run_git(project, ["grep", "-n", "--fixed-strings", "--", term])
        except subprocess.CalledProcessError:
            continue
        for line in output.splitlines():
            if len(matches) >= limit:
                break
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            file_path, lineno_text, text = parts
            try:
                lineno = int(lineno_text)
            except ValueError:
                continue
            matches.append((file_path, lineno, text))
    return matches


def read_project_file(project: Path, file_path: str, cache: dict[str, list[str]]) -> list[str] | None:
    if file_path in cache:
        return cache[file_path]
    source_path = project / file_path
    if not source_path.is_file():
        return None
    try:
        lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    cache[file_path] = lines
    return lines


def build_context_snippets(
    *,
    project: Path | None,
    patch: dict[str, Any],
    diff_text: str,
    cards: list[dict[str, Any]],
    max_snippets: int,
    radius: int,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    files = patch.get("files", [])
    if project is None or not isinstance(files, list):
        return "No source context snippets: project path unavailable.", [], context_coverage(cards, None)

    file_cache: dict[str, list[str]] = {}
    snippets: list[str] = []
    metadata: list[dict[str, Any]] = []
    snippet_bodies: list[str] = []

    def existing_ref(file_path: str, line: int) -> str | None:
        for item in metadata:
            if item.get("file") == file_path and item.get("start") <= line <= item.get("end"):
                return snippet_ref(item)
        return None

    def existing_overlap_ref(file_path: str, start: int, end: int) -> str | None:
        for item in metadata:
            if item.get("file") != file_path:
                continue
            if start <= item.get("end") and end >= item.get("start"):
                return snippet_ref(item)
        return None

    def add_window(file_path: str, start: int, end: int, reason: str) -> tuple[str | None, str | None]:
        found = existing_overlap_ref(file_path, start, end)
        if found is not None:
            return found, None
        if len(metadata) >= max_snippets:
            return None, "snippet budget exhausted"
        lines = read_project_file(project, file_path, file_cache)
        if not lines:
            return None, "file unavailable"
        bounded_start = max(1, start)
        bounded_end = min(len(lines), end)
        if bounded_start > bounded_end:
            return None, "window outside file"
        body = "\n".join(f"{lineno:5d}: {lines[lineno - 1]}" for lineno in range(bounded_start, bounded_end + 1))
        snippets.append(f"### {file_path}:{bounded_start}-{bounded_end}\n\n```text\n{body}\n```")
        metadata.append({
            "file": file_path,
            "start": bounded_start,
            "end": bounded_end,
            "reason": reason,
        })
        snippet_bodies.append(body)
        return snippet_ref(metadata[-1]), None

    def add_snippet(file_path: str, line: int, reason: str) -> tuple[str | None, str | None]:
        found = existing_ref(file_path, line)
        if found is not None:
            return found, None
        return add_window(file_path, line - radius, line + radius, reason)

    added_by_file = added_lines_by_file(diff_text)
    for file_path in files:
        if not isinstance(file_path, str):
            continue
        lines = read_project_file(project, file_path, file_cache)
        if lines is None:
            continue
        added_lines = added_by_file.get(file_path, [])
        if added_lines:
            windows = merge_windows((max(1, line - radius), line + radius) for line in added_lines[:3])
        else:
            windows = [(1, min(radius * 2 + 1, 80))]
        for start, end in windows:
            if len(metadata) >= min(6, max_snippets):
                break
            add_window(file_path, start, end, "changed-line context")
        if len(metadata) >= min(6, max_snippets):
            break

    coverage = context_coverage(
        cards,
        project,
        files=[path for path in files if isinstance(path, str)],
        file_cache=file_cache,
        add_snippet=add_snippet,
        snippet_bodies=snippet_bodies,
        search_terms=extract_search_terms(diff_text, cards),
    )

    if not snippets:
        return "No source context snippets found for changed files.", [], coverage
    return "\n\n".join(snippets), metadata, coverage


def context_coverage(
    cards: list[dict[str, Any]],
    project: Path | None,
    *,
    files: list[str] | None = None,
    file_cache: dict[str, list[str]] | None = None,
    add_snippet: Any | None = None,
    snippet_bodies: list[str] | None = None,
    search_terms: list[str] | None = None,
) -> list[dict[str, Any]]:
    coverage: list[dict[str, Any]] = []
    files = files or []
    file_cache = file_cache or {}
    snippet_bodies = snippet_bodies or []
    search_terms = search_terms or []

    for card in cards:
        card_id = card.get("id")
        if not isinstance(card_id, str):
            continue
        requirements = card.get("requires_context", [])
        if not isinstance(requirements, list):
            requirements = []
        required_entries: list[dict[str, Any]] = []
        for requirement in requirements:
            if not isinstance(requirement, str) or not requirement:
                continue
            patterns = context_patterns(requirement, card)
            compiled = compile_context_patterns(patterns)
            evidence: list[str] = []
            notes: list[str] = []

            for body_index, body in enumerate(snippet_bodies, start=1):
                if any(pattern.search(body) for pattern in compiled):
                    evidence.append(f"context-snippet:{body_index}")
                    if len(evidence) >= MAX_CONTEXT_EVIDENCE_PER_REQUIREMENT:
                        break

            if not evidence and project is not None and add_snippet is not None:
                for file_path in files:
                    lines = read_project_file(project, file_path, file_cache)
                    if not lines:
                        continue
                    for lineno, line in enumerate(lines, start=1):
                        if any(pattern.search(line) for pattern in compiled):
                            ref, note = add_snippet(file_path, lineno, f"context coverage: {card_id}/{requirement}")
                            if ref:
                                evidence.append(ref)
                            elif note:
                                notes.append(note)
                            break
                    if evidence:
                        break

            if not evidence and project is not None and add_snippet is not None and should_repo_search(requirement):
                for file_path, lineno, _text in git_grep_matches(project, search_terms, limit=12):
                    ref, note = add_snippet(file_path, lineno, f"repo context coverage: {card_id}/{requirement}")
                    if ref:
                        evidence.append(ref)
                    elif note:
                        notes.append(note)
                    if len(evidence) >= MAX_CONTEXT_EVIDENCE_PER_REQUIREMENT:
                        break

            evidence = unique_strings(evidence)[:MAX_CONTEXT_EVIDENCE_PER_REQUIREMENT]
            notes = unique_strings(notes)
            status = "evidence_in_packet" if evidence else "missing_from_packet"
            if project is None:
                notes.append("project path unavailable")
            required_entries.append({
                "name": requirement,
                "status": status,
                "evidence": evidence,
                "search_terms": search_terms if should_repo_search(requirement) else [],
                "notes": notes[:3],
            })
        coverage.append({
            "card": card_id,
            "required": required_entries,
            "missing": [entry["name"] for entry in required_entries if entry["status"] != "evidence_in_packet"],
        })
    return coverage


def context_coverage_section(coverage: list[dict[str, Any]]) -> str:
    if not coverage:
        return "No selected rule cards declared required context."
    lines = [
        "Context coverage is orchestrator-provided evidence inventory, not proof of safety.",
        "If a selected card requirement is missing from the packet, mark that check inconclusive instead of guessing.",
    ]
    for card in coverage:
        card_id = card.get("card")
        if not isinstance(card_id, str):
            continue
        lines.append(f"\n- `{card_id}`")
        required = card.get("required", [])
        if not isinstance(required, list) or not required:
            lines.append("  - no required context declared")
            continue
        for entry in required:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            status = entry.get("status")
            evidence = entry.get("evidence")
            evidence_text = ", ".join(f"`{item}`" for item in evidence) if isinstance(evidence, list) and evidence else "none"
            lines.append(f"  - `{name}`: {status}; evidence: {evidence_text}")
    return "\n".join(lines)


def deferred_rule_cards_section(cards: list[dict[str, Any]]) -> str:
    if not cards:
        return "No matched rule cards were deferred by the active-card budget."
    lines = [
        "Matched but deferred rule cards are recorded for auditability only.",
        "They are not part of active Rule Card Coverage for this packet.",
    ]
    for card in cards:
        card_id = card.get("id")
        if not isinstance(card_id, str):
            continue
        trigger_text = _selection_trigger_text(card)
        first_trigger = next((line for line in trigger_text.splitlines() if line), "no trigger recorded")
        lines.append(f"- `{card_id}`: deferred; first trigger: `{first_trigger}`")
    return "\n".join(lines)


def card_section(skill_dir: Path, card: dict[str, Any]) -> str:
    card_id = card.get("id")
    card_path = card.get("card")
    if not isinstance(card_id, str) or not card_id:
        raise ValueError("rule card entry missing id")
    if not isinstance(card_path, str) or not card_path:
        raise ValueError(f"rule card {card_id}: missing card path")
    text = load_ref(skill_dir, card_path)
    trigger_lines = "\n".join(f"- {trigger}" for trigger in card.get("triggers", []))
    if not trigger_lines:
        trigger_lines = "- selected by manifest trigger"
    required_context = card.get("requires_context", [])
    required_lines = "\n".join(f"- {item}" for item in required_context if isinstance(item, str))
    if not required_lines:
        required_lines = "- none declared"
    prefix = (
        f"Selected card: `{card_id}`\n\n"
        f"Trigger evidence:\n{trigger_lines}\n\n"
        f"Required context inventory keys:\n{required_lines}\n\n"
    )
    return section(f"selected-rule-card:{card_id}", prefix + text)


def packet_metadata(
    manifest: dict[str, Any],
    patch: dict[str, Any],
    context_metadata: list[dict[str, Any]] | None = None,
    context_requirements: list[dict[str, Any]] | None = None,
    focused_hunks: list[dict[str, Any]] | None = None,
    focused_obligations: list[dict[str, str]] | None = None,
    matched_rule_cards: list[dict[str, Any]] | None = None,
    deferred_cards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    paths = patch.get("paths") if isinstance(patch.get("paths"), dict) else {}
    active_cards = patch.get("rule_cards", [])
    matched_cards = matched_rule_cards or active_cards
    deferred = deferred_cards or []
    return {
        "schema": SCHEMA,
        "mode": manifest.get("mode"),
        "slug": manifest.get("slug"),
        "patch": patch.get("n"),
        "total": patch.get("total"),
        "hash": patch.get("hash"),
        "short_hash": patch.get("short_hash"),
        "subject": patch.get("subject"),
        "files": patch.get("files", []),
        "paths": paths,
        "rule_cards": active_cards,
        "matched_rule_cards": matched_cards,
        "deferred_rule_cards": deferred,
        "rule_card_budget": {
            "mode": "active-post-selection",
            "max_active": MAX_ACTIVE_RULE_CARDS,
            "matched_count": len(matched_cards) if isinstance(matched_cards, list) else 0,
            "active_count": len(active_cards) if isinstance(active_cards, list) else 0,
            "deferred_count": len(deferred) if isinstance(deferred, list) else 0,
        },
        "focused_hunks_by_rule": focused_hunks or [],
        "focused_review_obligations": focused_obligations or [],
        "context_snippets": context_metadata or [],
        "context_coverage": context_requirements or [],
    }


def build_packet(
    skill_dir: Path,
    manifest: dict[str, Any],
    patch: dict[str, Any],
    project: Path | None,
) -> tuple[str, dict[str, Any]]:
    diff = patch_diff(project, patch)
    cards = patch.get("rule_cards", [])
    if not isinstance(cards, list):
        raise ValueError("patch rule_cards must be a list")
    normalized_cards = [card for card in cards if isinstance(card, dict)]
    matched_cards = expand_rule_card_triggers(normalized_cards, load_rule_index_cards(skill_dir))
    expanded_cards = active_rule_cards(matched_cards, patch)
    deferred_cards = deferred_rule_cards(matched_cards, expanded_cards)
    focused_hunks = focused_hunks_by_rule(diff, expanded_cards)
    context_text, context_metadata, context_requirements = build_context_snippets(
        project=project,
        patch=patch,
        diff_text=diff,
        cards=expanded_cards,
        max_snippets=12,
        radius=20,
    )
    focused_obligations = focused_review_obligations(focused_hunks)
    metadata_patch = dict(patch)
    metadata_patch["rule_cards"] = expanded_cards
    metadata = packet_metadata(
        manifest,
        metadata_patch,
        context_metadata,
        context_requirements,
        focused_hunks,
        focused_obligations,
        matched_cards,
        deferred_cards,
    )
    reviewer_base = load_ref(skill_dir, "refs/reviewer-base.md")
    output_format = load_ref(skill_dir, "refs/output-format-mini.md")

    parts = [
        "<!-- Generated by scripts/assemble_review_packet.py; do not hand-edit. -->\n",
        section("packet-metadata", "```json\n" + json.dumps(metadata, indent=2, sort_keys=True) + "\n```"),
        section("reviewer-base", reviewer_base),
        section("output-format-mini", output_format),
        section("focused-review-obligations", focused_review_obligations_section(focused_hunks)),
        section("focused-rule-evidence", focused_hunks_section(focused_hunks)),
        section("context-snippets", context_text),
        section("context-coverage", context_coverage_section(context_requirements)),
        section("deferred-rule-cards", deferred_rule_cards_section(deferred_cards)),
        "<!-- BEGIN selected-rule-cards -->\n",
    ]
    if expanded_cards:
        for card in expanded_cards:
            parts.append(card_section(skill_dir, card))
    else:
        parts.append("No triggered rule cards. Apply the reviewer base contract to the patch evidence.\n")
    parts.append("<!-- END selected-rule-cards -->\n")

    message = commit_message(project, patch)
    paths = patch.get("paths") if isinstance(patch.get("paths"), dict) else {}
    checker_lines = ["Checker artifacts recorded by the orchestrator:"]
    for key in ("build", "dtbinding", "block"):
        value = paths.get(key)
        if not isinstance(value, str) or not value:
            continue
        if key == "dtbinding" and project is not None and not (project / value).exists():
            continue
        checker_lines.append(f"- {key}: `{value}`")

    # Inline checker artifact content so subagents can see build/checkpatch
    # output without needing on-demand reads of external files.
    _CHECKER_INLINE_KEYS = ("build", "dtbinding")
    _CHECKER_MAX_LINES = 80
    for key in _CHECKER_INLINE_KEYS:
        value = paths.get(key)
        if not isinstance(value, str) or not value:
            continue
        content = read_artifact(project, value)
        if not content:
            continue
        lines = content.splitlines()
        if len(lines) > _CHECKER_MAX_LINES:
            truncated = lines[:_CHECKER_MAX_LINES]
            truncated.append(f"... ({len(lines) - _CHECKER_MAX_LINES} more lines truncated)")
            content = "\n".join(truncated)
        checker_lines.append(f"\n### {key} output\n```\n{content}\n```")

    # Include shared tests file (checkpatch + get_maintainer) if available.
    slug = manifest.get("slug", "")
    if slug and project is not None:
        tests_path = project / "tmp" / f"tests_{slug}.txt"
        if tests_path.exists():
            tests_content = tests_path.read_text(encoding="utf-8", errors="replace").rstrip()
            if tests_content:
                lines = tests_content.splitlines()
                if len(lines) > _CHECKER_MAX_LINES:
                    truncated = lines[:_CHECKER_MAX_LINES]
                    truncated.append(f"... ({len(lines) - _CHECKER_MAX_LINES} more lines truncated)")
                    tests_content = "\n".join(truncated)
                checker_lines.append(f"\n### checkpatch / tests output\n```\n{tests_content}\n```")

    parts.extend([
        section("commit-message", "```text\n" + message.rstrip() + "\n```"),
        section("checker-evidence", "\n".join(checker_lines)),
        section("patch-diff", "```diff\n" + diff.rstrip() + "\n```"),
    ])
    return "\n".join(parts).rstrip() + "\n", metadata


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble a compact per-patch reviewer packet")
    parser.add_argument("--skill-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--patch", required=True, type=int, dest="patch_number")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--project", type=Path, default=None, help="Kernel project path for git fallbacks and tmp artifacts")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    skill_dir = args.skill_dir.expanduser().resolve()
    project = args.project.expanduser().resolve() if args.project else None
    try:
        manifest = load_manifest(args.manifest.expanduser())
        patch = select_patch(manifest, args.patch_number)
        packet, metadata = build_packet(skill_dir, manifest, patch, project)
        output = args.output.expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(packet, encoding="utf-8")
        json_output = args.json_output.expanduser() if args.json_output else None
        if json_output is not None:
            json_output.parent.mkdir(parents=True, exist_ok=True)
            json_output.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"assemble_review_packet.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
