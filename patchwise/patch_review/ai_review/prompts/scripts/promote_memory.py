#!/usr/bin/env python3
"""Deterministic promotion/demotion gate for curated review memory.

Promotion (draft -> active) and demotion (active -> draft) decisions are
otherwise left to soft LLM judgment, which defaults entries to ``draft`` and
leaves reusable patterns excluded from normal reviews.  This helper applies a
deterministic gate keyed on fields that ``memory_lint.py`` already validates so
that qualifying entries graduate to ``active`` and contradicted entries fall
back to ``draft`` without silent data loss.

Usage:
  promote_memory.py --check                 # list promotion candidates (dry run)
  promote_memory.py --auto                  # promote qualifying drafts
  promote_memory.py --demote-check          # list active entries flagged contradicted
  promote_memory.py --demote MEM-#### ...   # demote named active entries to draft
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ENTRY_RE = re.compile(r"^### (MEM-\d{4}): .+$", re.MULTILINE)
FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z -]*):\s*(.*)$")
STATUS_DIRS = ("active", "draft", "deprecated")
TOPIC_FILES = ("patch-scope.md", "commit-message.md", "dt-bindings.md", "subsystem-specific.md")

_EMPTY_VALUES = {"", "none", "n/a", "na", "tbd", "todo", "-"}
# A real maintainer-evidence bullet should name a person/bot and cite a lore
# message-id, lore link, or an ISO date.  Markers below also satisfy the
# "repeated/confirmed evidence" branch of the promotion gate.
_EVIDENCE_CITATION_RE = re.compile(
    r"(lore\.kernel\.org|message-id|msgid|<[^>]+@[^>]+>|\b\d{4}-\d{2}-\d{2}\b)",
    re.IGNORECASE,
)
_CONFIRMED_MARKER_RE = re.compile(
    r"(missed[- ]by[- ]us|bot[- ]confirmed|confirmed by|maintainer confirmed|"
    r"repeated(ly)?|recurring|seen again)",
    re.IGNORECASE,
)
_CONTRADICTED_MARKER_RE = re.compile(
    r"(contradict|overturn|maintainer disagreed|false[- ]positive confirmed|"
    r"refuted|retracted|no longer valid)",
    re.IGNORECASE,
)
_STRONG_CONFIDENCE = {"medium", "high"}


def split_entries(path: Path) -> list[tuple[str, str]]:
    content = path.read_text(encoding="utf-8")
    matches = list(ENTRY_RE.finditer(content))
    entries: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        entries.append((match.group(1), content[start:end].strip()))
    return entries


def parse_fields(entry_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in entry_text.splitlines():
        match = FIELD_RE.match(line)
        if match:
            fields[match.group(1)] = match.group(2).strip()
    return fields


def field_bullets(entry_text: str, field_name: str) -> list[str]:
    lines = entry_text.splitlines()
    bullets: list[str] = []
    for index, line in enumerate(lines):
        if line.startswith(f"{field_name}:"):
            for following in lines[index + 1 :]:
                if FIELD_RE.match(following) or following.startswith("### "):
                    break
                if following.startswith("- "):
                    bullets.append(following[2:].strip())
            break
    return bullets


def _has_real_content(bullets: list[str]) -> bool:
    return any(bullet.strip().lower() not in _EMPTY_VALUES for bullet in bullets)


def promotion_reasons(entry_text: str) -> tuple[bool, list[str]]:
    """Return (qualifies, reasons) for a draft -> active promotion."""
    fields = parse_fields(entry_text)
    reasons: list[str] = []

    evidence = field_bullets(entry_text, "Maintainer evidence")
    evidence_text = " ".join(evidence)
    has_citation = bool(_EVIDENCE_CITATION_RE.search(evidence_text))
    has_marker = bool(_CONFIRMED_MARKER_RE.search(evidence_text))
    if not _has_real_content(evidence):
        reasons.append("no real maintainer evidence")
    elif not (has_citation or has_marker):
        reasons.append("maintainer evidence lacks lore/msg-id/date or confirmed marker")

    guards = field_bullets(entry_text, "False-positive guards")
    if not _has_real_content(guards):
        reasons.append("no real false-positive guards")

    confidence = fields.get("Confidence", "").lower()
    if confidence not in _STRONG_CONFIDENCE and not has_marker:
        reasons.append("confidence below medium and no confirmed/missed-by-us marker")

    return (not reasons, reasons)


def contradiction_marker(entry_text: str) -> bool:
    return bool(_CONTRADICTED_MARKER_RE.search(entry_text))


def iter_entries(memory_dir: Path, status: str):
    for topic in TOPIC_FILES:
        path = memory_dir / status / topic
        if not path.is_file():
            continue
        for memory_id, entry in split_entries(path):
            yield memory_id, entry, path


def _move(memory_dir: Path, memory_id: str, status: str) -> int:
    mover = Path(__file__).with_name("move_memory_entry.py")
    return subprocess.run(
        [sys.executable, str(mover), memory_id, "--status", status, "--memory-dir", str(memory_dir)],
        text=True,
    ).returncode


def cmd_check(memory_dir: Path, apply: bool) -> int:
    candidates: list[str] = []
    skipped: list[tuple[str, list[str]]] = []
    for memory_id, entry, _path in iter_entries(memory_dir, "draft"):
        qualifies, reasons = promotion_reasons(entry)
        if qualifies:
            candidates.append(memory_id)
        else:
            skipped.append((memory_id, reasons))

    if candidates:
        print("Promotion candidates (draft -> active):")
        for memory_id in candidates:
            print(f"  {memory_id}")
    else:
        print("No draft entries qualify for promotion.")

    if not apply:
        if skipped:
            print("\nHeld in draft:")
            for memory_id, reasons in skipped:
                print(f"  {memory_id}: {'; '.join(reasons)}")
        return 0

    failed = 0
    for memory_id in candidates:
        if _move(memory_dir, memory_id, "active") != 0:
            failed += 1
    return 1 if failed else 0


def cmd_demote_check(memory_dir: Path) -> int:
    flagged = [
        memory_id
        for memory_id, entry, _path in iter_entries(memory_dir, "active")
        if contradiction_marker(entry)
    ]
    if flagged:
        print("Active entries flagged with contradiction markers (review for demotion):")
        for memory_id in flagged:
            print(f"  {memory_id}")
    else:
        print("No active entries carry contradiction markers.")
    return 0


def cmd_demote(memory_dir: Path, memory_ids: list[str]) -> int:
    active_ids = {memory_id for memory_id, _entry, _path in iter_entries(memory_dir, "active")}
    failed = 0
    for memory_id in memory_ids:
        if memory_id not in active_ids:
            print(f"{memory_id} is not an active entry; skipping", file=sys.stderr)
            failed += 1
            continue
        if _move(memory_dir, memory_id, "draft") != 0:
            failed += 1
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--memory-dir", type=Path, default=Path(__file__).resolve().parents[1] / "refs" / "memory")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="List draft entries that qualify for promotion (dry run)")
    group.add_argument("--auto", action="store_true", help="Promote qualifying draft entries to active")
    group.add_argument("--demote-check", action="store_true", help="List active entries flagged contradicted")
    group.add_argument("--demote", nargs="+", metavar="MEM-####", help="Demote named active entries to draft")
    args = parser.parse_args(argv)

    if args.check:
        return cmd_check(args.memory_dir, apply=False)
    if args.auto:
        return cmd_check(args.memory_dir, apply=True)
    if args.demote_check:
        return cmd_demote_check(args.memory_dir)
    return cmd_demote(args.memory_dir, args.demote)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
