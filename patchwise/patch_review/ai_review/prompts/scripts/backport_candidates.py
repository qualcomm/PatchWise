#!/usr/bin/env python3
"""Suggest how to back-port active memory entries into base rule files.

Goal: keep prompt/rule files small.  Back-porting verbatim bloats the brief and
hurts review accuracy, so this tool biases toward *subsume* (cover the case with
an existing rule, add nothing) and *generalize* (broaden an existing rule's
wording) over *add*.  For each active memory entry it finds the best-matching
existing rule section and classifies the recommended action.

It is advisory only: it never edits files.  Use it to build a back-port
worklist, then make the rule edits by hand following the printed action.

Usage:
  backport_candidates.py                       # full report
  backport_candidates.py --only logic          # only logic/structural entries
  backport_candidates.py --min-score 0.18      # tune the subsume/new threshold
  backport_candidates.py --brief-budget 3800   # warn if assembled brief exceeds
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
REFS = SKILL_DIR / "refs"
ACTIVE = REFS / "memory" / "active"

# Rule files that back-ported *logic/structural* patterns belong in.
RULE_FILES = [
    "code-logic.md",
    "hardware-eng.md",
    "dt-binding.md",
    "dt-driver.md",
    "commit-message.md",
    "special-cases.md",
    "coding-style.md",
    "core.md",
    "gate-rules.md",
]

ENTRY_RE = re.compile(r"^### (MEM-\d{4}): (.+)$", re.MULTILINE)
FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z -]*):\s*(.*)$")
HEADING_RE = re.compile(r"^(#{2,4})\s+(.*)$")
WORD_RE = re.compile(r"[a-z_][a-z0-9_]{2,}")

# Entries whose value is contextual preference/convention, not a transferable
# invariant, should usually STAY in memory.  Flag them so we don't bloat rules.
_PREFERENCE_RE = re.compile(
    r"(prefer|convention|wording|style|maintainer likes|this list|"
    r"naming|cosmetic|subjective)",
    re.IGNORECASE,
)
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "when", "from", "not", "use",
    "are", "any", "all", "but", "into", "than", "via", "per", "its", "has",
    "review", "action", "flag", "check", "patch", "code", "rule", "entry",
    "memory", "should", "must", "does", "can", "may", "one", "each", "every",
}


def tokens(text: str) -> set[str]:
    return {w for w in WORD_RE.findall(text.lower()) if w not in _STOPWORDS}


def split_entries(path: Path) -> list[tuple[str, str, str]]:
    content = path.read_text(encoding="utf-8")
    matches = list(ENTRY_RE.finditer(content))
    out: list[tuple[str, str, str]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        out.append((m.group(1), m.group(2), content[start:end].strip()))
    return out


def entry_signal(entry_text: str) -> str:
    """Text the matcher keys on: Triggers + Review action bullets + title."""
    keep: list[str] = []
    grab = False
    for line in entry_text.splitlines():
        head = FIELD_RE.match(line)
        if head:
            grab = head.group(1) in ("Triggers", "Review action")
            continue
        if grab and line.strip().startswith("- "):
            keep.append(line.strip()[2:])
    return " ".join(keep)


def is_preference(entry_text: str) -> bool:
    scope = ""
    for line in entry_text.splitlines():
        m = FIELD_RE.match(line)
        if m and m.group(1) == "Scope":
            scope = m.group(2)
            break
    return bool(_PREFERENCE_RE.search(entry_text)) and "subsystem:" in scope


def index_rule_sections() -> list[tuple[str, str, set[str]]]:
    """Return (file, heading, token-set) for each rule section."""
    sections: list[tuple[str, str, set[str]]] = []
    for name in RULE_FILES:
        path = REFS / name
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        heads = [(i, m.group(2)) for i, line in enumerate(lines) if (m := HEADING_RE.match(line))]
        for idx, (start, title) in enumerate(heads):
            end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
            body = "\n".join(lines[start:end])
            sections.append((name, title, tokens(body)))
    return sections


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def best_match(sig: set[str], sections: list[tuple[str, str, set[str]]]):
    best = (0.0, "", "")
    for name, title, toks in sections:
        score = jaccard(sig, toks)
        if score > best[0]:
            best = (score, name, title)
    return best


def classify(score: float, min_score: float) -> str:
    if score >= min_score * 2:
        return "SUBSUME (covered; add nothing or 1 example to existing rule)"
    if score >= min_score:
        return "GENERALIZE (broaden existing rule wording; net lines ~0)"
    if score >= min_score * 0.5:
        return "MERGE (fold with near-match rule; do not add standalone)"
    return "NEW (genuinely new class; write generic from day one)"


def assembled_brief_lines() -> int | None:
    """Best-effort current brief size; None if not assembled."""
    candidate = Path("/tmp/a.md")
    if candidate.is_file():
        return sum(1 for _ in candidate.open())
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=["logic", "all"], default="all",
                        help="logic = skip subsystem preference/convention entries")
    parser.add_argument("--min-score", type=float, default=0.18,
                        help="Jaccard threshold separating generalize from new")
    parser.add_argument("--brief-budget", type=int, default=3800,
                        help="warn if the assembled brief (/tmp/a.md) exceeds this")
    args = parser.parse_args(argv)

    sections = index_rule_sections()
    rows: list[tuple] = []
    skipped_pref = 0

    for topic in sorted(ACTIVE.glob("*.md")):
        for memory_id, title, body in split_entries(topic):
            if args.only == "logic" and is_preference(body):
                skipped_pref += 1
                continue
            sig = tokens(entry_signal(body) + " " + title)
            score, fname, heading = best_match(sig, sections)
            action = classify(score, args.min_score)
            rows.append((action, memory_id, score, fname, heading, title))

    order = {"SUBSUME": 0, "GENERALIZE": 1, "MERGE": 2, "NEW": 3}
    rows.sort(key=lambda r: (order[r[0].split()[0]], -r[2]))

    print(f"{'ACTION':<11} {'MEM':<9} {'SCORE':<6} {'BEST RULE TARGET':<40} ENTRY")
    print("-" * 110)
    for action, mid, score, fname, heading, title in rows:
        tag = action.split()[0]
        target = f"{fname} \u00a7 {heading}"[:40]
        print(f"{tag:<11} {mid:<9} {score:<6.3f} {target:<40} {title[:48]}")

    counts = {k: 0 for k in order}
    for action, *_ in rows:
        counts[action.split()[0]] += 1
    print("-" * 110)
    print("Summary: " + ", ".join(f"{k}={counts[k]}" for k in order)
          + (f", preference-skipped={skipped_pref}" if args.only == "logic" else ""))
    print("Bias: prefer SUBSUME > GENERALIZE > MERGE > NEW. Each NEW rule must be "
          "generic (pattern + guard + severity), never a single-incident anecdote.")

    brief = assembled_brief_lines()
    if brief is not None:
        flag = "OK" if brief <= args.brief_budget else "OVER BUDGET"
        print(f"Assembled brief (/tmp/a.md): {brief} lines / budget {args.brief_budget} -> {flag}")
    else:
        print("Brief size unknown: run assemble_rules.py --output /tmp/a.md to enable the budget check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(argv=__import__("sys").argv[1:]))
