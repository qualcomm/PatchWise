#!/usr/bin/env python3
"""Assemble review rules briefs for the review-commits skill.

The orchestrator uses this script to build per-patch Mode A/B
``tmp/patch_<N>_rules.md`` files and Mode C ``tmp/review_<slug>_file_rules.md``
files from stable rule refs plus only directly relevant memory entries. It is
kept small and dependency-free so rules assembly is deterministic and auditable.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Iterable

PATCH_BASE_REFS = (
    "core.md",
    "coding-style.md",
    "code-logic.md",
    "commit-message.md",
    "gate-rules.md",
    "special-cases.md",
)
MODE_C_BASE_REFS = (
    "core.md",
    "coding-style.md",
    "code-logic.md",
    "gate-rules.md",
    "special-cases.md",
)

MEMORY_FILES = {
    "patch-scope": "patch-scope.md",
    "commit-message": "commit-message.md",
    "dt-bindings": "dt-bindings.md",
    "subsystem-specific": "subsystem-specific.md",
}
MODE_C_FORBIDDEN_MEMORY = {"patch-scope", "commit-message"}
VALID_MEMORY_STATUSES = {"active", "draft", "deprecated", "all"}
STATUS_DIRS = ("active", "draft", "deprecated")
MEMORY_ENTRY_RE = re.compile(r"(?ms)^### MEM-\d+: .*?(?=^### MEM-\d+: |\Z)")
STATUS_RE = re.compile(r"(?m)^Status:\s*([A-Za-z-]+)\s*$")
SCOPE_RE = re.compile(r"(?m)^Scope:\s*(.+)$")

MODE_C_PREAMBLE = """## Mode C — Single-File Review Overrides

This rules brief is for Mode C. Review exactly the source file named by the
orchestrator, not a git patch. Apply the included coding-style, code-logic,
DT/DT-binding when triggered, hardware when triggered, three-gate, output-format,
and special-case rules with these overrides:

- There is no patch hash, series summary, contamination note, commit message, or
  patch-scope review; ignore patch-only Step 1 hash checks, Step 3a, and Step 3e.
- Read the full target file and the provided related headers/Kconfig/Makefile
  context before applying the checklists.
- Use the Mode C per-file block format from refs/core.md and write
  `tmp/review_<slug>_file_block.html` plus the `file: DONE` sidecar line.
- Keep DT and Hardware Engineering sections present in the output; write the
  explicit Not applicable body when the trigger is absent.
"""


def split_csv(values: Iterable[str] | None) -> list[str]:
    items: list[str] = []
    for value in values or []:
        for item in value.split(","):
            item = item.strip()
            if item:
                items.append(item)
    return items


def normalize_paths(values: Iterable[str] | None) -> list[str]:
    paths: list[str] = []
    for value in values or []:
        value = value.strip()
        if value:
            paths.append(value)
    return paths


def read_ref(refs_dir: Path, name: str) -> str:
    path = refs_dir / name
    if not path.is_file():
        raise FileNotFoundError(f"missing required rule ref: {path}")
    return path.read_text(encoding="utf-8")


def entry_status(entry: str) -> str | None:
    match = STATUS_RE.search(entry)
    if not match:
        return None
    return match.group(1).lower()


def entry_scope(entry: str) -> str | None:
    match = SCOPE_RE.search(entry)
    if not match:
        return None
    return match.group(1).strip()


def split_scope_terms(scope: str | None) -> list[tuple[str, str]]:
    if not scope:
        return []
    terms: list[tuple[str, str]] = []
    for token in scope.split():
        token = token.strip()
        if not token:
            continue
        if ":" not in token:
            terms.append((token.lower(), ""))
            continue
        kind, value = token.split(":", 1)
        terms.append((kind.lower(), value.strip()))
    return terms


def _path_parts(path: str) -> list[str]:
    return [part.lower() for part in Path(path).parts if part not in {"", "."}]


def path_matches_subsystem(path: str, subsystem: str) -> bool:
    subsystem_parts = [part for part in subsystem.lower().split("/") if part]
    if not subsystem_parts:
        return False
    path_parts = _path_parts(path)
    width = len(subsystem_parts)
    for start in range(len(path_parts) - width + 1):
        if path_parts[start:start + width] == subsystem_parts:
            return True
    return False


def entry_matches_scope(entry: str, scope_files: list[str]) -> bool:
    terms = split_scope_terms(entry_scope(entry))
    if not terms or any(kind == "general" for kind, _value in terms):
        return True
    if not scope_files:
        return True

    file_patterns = [value for kind, value in terms if kind == "file-pattern" and value]
    subsystems = [value for kind, value in terms if kind == "subsystem" and value]

    if file_patterns and not any(
        fnmatch.fnmatchcase(path, pattern)
        for pattern in file_patterns
        for path in scope_files
    ):
        return False

    if subsystems and not any(
        path_matches_subsystem(path, subsystem)
        for subsystem in subsystems
        for path in scope_files
    ):
        return False

    return True


def split_layout_exists(memory_dir: Path) -> bool:
    return any((memory_dir / status).is_dir() for status in STATUS_DIRS)


def statuses_to_dirs(statuses: set[str]) -> list[str]:
    if "all" in statuses:
        return list(STATUS_DIRS)
    return [status for status in STATUS_DIRS if status in statuses]


def select_memory_entries(
    memory_dir: Path,
    filename: str,
    statuses: set[str],
    scope_files: list[str],
) -> list[tuple[str, str]]:
    if split_layout_exists(memory_dir):
        selected: list[tuple[str, str]] = []
        status_dirs = statuses_to_dirs(statuses)
        missing_paths = [
            memory_dir / status_dir / filename
            for status_dir in status_dirs
            if not (memory_dir / status_dir / filename).is_file()
        ]
        if missing_paths:
            missing = ", ".join(str(path) for path in missing_paths)
            raise FileNotFoundError(f"missing split-layout memory file(s): {missing}")

        for status_dir in status_dirs:
            path = memory_dir / status_dir / filename
            text = path.read_text(encoding="utf-8")
            for match in MEMORY_ENTRY_RE.finditer(text):
                entry = match.group(0).strip()
                status = entry_status(entry)
                # The directory is authoritative for split layout: an entry in
                # active/ is active regardless of its in-body Status: line. A
                # missing line is tolerated, but a line that *contradicts* the
                # directory is a data error — fail loudly rather than silently
                # drop the entry (the old `status == status_dir` guard did the
                # latter, hiding mislabeled or unlabeled entries from reviewers).
                if status is not None and status != status_dir:
                    raise ValueError(
                        f"memory entry in {status_dir}/{filename} declares "
                        f"Status: {status}; move it to {status}/{filename} or "
                        f"correct the Status: line"
                    )
                if entry_matches_scope(entry, scope_files):
                    selected.append((f"refs/memory/{status_dir}/{filename}", entry))
        return selected

    path = memory_dir / filename
    if not path.is_file():
        raise FileNotFoundError(f"missing memory ref: {path}")

    include_all = "all" in statuses
    text = path.read_text(encoding="utf-8")
    selected = []
    for match in MEMORY_ENTRY_RE.finditer(text):
        entry = match.group(0).strip()
        status = entry_status(entry)
        if (include_all or (status in statuses)) and entry_matches_scope(entry, scope_files):
            selected.append((f"refs/memory/{filename}", entry))
    return selected


def add_section(parts: list[str], title: str, body: str) -> None:
    parts.append(f"\n\n<!-- BEGIN {title} -->\n")
    parts.append(body.rstrip())
    parts.append(f"\n<!-- END {title} -->\n")


def build_rules(
    skill_dir: Path,
    include_dt: bool,
    include_dt_driver: bool,
    include_hardware: bool,
    memory_categories: list[str],
    memory_statuses: set[str],
    scope_files: list[str],
    mode_c: bool,
) -> str:
    refs_dir = skill_dir / "refs"
    memory_dir = refs_dir / "memory"
    parts: list[str] = [
        "<!-- Generated by scripts/assemble_rules.py; do not hand-edit this temp file. -->\n",
        "<!-- Memory policy: include only requested categories and selected statuses. -->\n",
    ]
    if scope_files:
        parts.append(
            "<!-- Memory scope files JSON: "
            + json.dumps(scope_files, ensure_ascii=True)
            + " -->\n"
        )

    if mode_c:
        add_section(parts, "mode-c-overrides", MODE_C_PREAMBLE)

    for ref_name in MODE_C_BASE_REFS if mode_c else PATCH_BASE_REFS:
        add_section(parts, f"refs/{ref_name}", read_ref(refs_dir, ref_name))

    if include_dt:
        add_section(parts, "refs/dt-binding.md", read_ref(refs_dir, "dt-binding.md"))

    if include_dt_driver:
        add_section(parts, "refs/dt-driver.md", read_ref(refs_dir, "dt-driver.md"))

    if include_hardware:
        add_section(parts, "refs/hardware-eng.md", read_ref(refs_dir, "hardware-eng.md"))

    seen_memory: set[str] = set()
    for category in memory_categories:
        if category in seen_memory:
            continue
        seen_memory.add(category)
        filename = MEMORY_FILES[category]
        entries = select_memory_entries(memory_dir, filename, memory_statuses, scope_files)
        status_label = ",".join(sorted(memory_statuses))
        if entries:
            grouped: dict[str, list[str]] = {}
            for section, entry in entries:
                grouped.setdefault(section, []).append(entry)
            for section, section_entries in grouped.items():
                add_section(parts, section, "\n\n".join(section_entries))
        else:
            if split_layout_exists(memory_dir) and "all" not in memory_statuses:
                dirs = statuses_to_dirs(memory_statuses)
                section = f"refs/memory/{'+'.join(dirs)}/{filename}"
            else:
                section = f"refs/memory/{filename}"
            if scope_files:
                body = (
                    f"No memory entries selected from refs/memory/{filename} for "
                    f"status={status_label} and scope-files="
                    f"{json.dumps(scope_files, ensure_ascii=True)}."
                )
            else:
                body = f"No memory entries selected from refs/memory/{filename} for status={status_label}."
            add_section(parts, section, body)

    return "".join(parts).lstrip() + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assemble a review-commits rules brief for patch or file reviews."
    )
    parser.add_argument(
        "--skill-dir",
        default=str(Path(__file__).resolve().parents[1]),
        help="Path to the review-commits skill directory. Defaults to this script's parent skill.",
    )
    parser.add_argument("--output", required=True, help="Output path for the generated rules brief")
    parser.add_argument("--mode-c", action="store_true", help="Assemble a single-file Mode C rules brief")
    parser.add_argument("--dt", action="store_true", help="Include full DT/DT-binding schema + DTS rules (refs/dt-binding.md)")
    parser.add_argument("--dt-driver", action="store_true", help="Include driver of_* API rules only (refs/dt-driver.md)")
    parser.add_argument("--hardware", action="store_true", help="Include hardware-engineering rules")
    parser.add_argument(
        "--memory",
        action="append",
        default=[],
        metavar="CATEGORY[,CATEGORY...]",
        help="Memory category to include: patch-scope, commit-message, dt-bindings, subsystem-specific",
    )
    parser.add_argument(
        "--memory-status",
        action="append",
        default=None,
        metavar="STATUS[,STATUS...]",
        help="Memory status to include; default: active. Use all only for maintenance/debugging.",
    )
    parser.add_argument(
        "--scope-file",
        action="append",
        default=[],
        metavar="PATH",
        help="Patch file path used to filter scoped memory entries",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    skill_dir = Path(args.skill_dir).expanduser().resolve()
    output = Path(args.output).expanduser()
    memory_categories = split_csv(args.memory)
    memory_statuses = set(split_csv(args.memory_status) or ["active"])
    scope_files = normalize_paths(args.scope_file)

    unknown_memory = sorted(set(memory_categories) - set(MEMORY_FILES))
    if unknown_memory:
        print(f"unknown memory categories: {', '.join(unknown_memory)}", file=sys.stderr)
        return 2

    if args.mode_c:
        forbidden = sorted(set(memory_categories) & MODE_C_FORBIDDEN_MEMORY)
        if forbidden:
            print(f"Mode C cannot include patch-only memory categories: {', '.join(forbidden)}", file=sys.stderr)
            return 2

    unknown_statuses = sorted(memory_statuses - VALID_MEMORY_STATUSES)
    if unknown_statuses:
        print(f"unknown memory statuses: {', '.join(unknown_statuses)}", file=sys.stderr)
        return 2

    if not skill_dir.is_dir():
        print(f"skill directory does not exist: {skill_dir}", file=sys.stderr)
        return 2

    try:
        rules = build_rules(
            skill_dir=skill_dir,
            include_dt=args.dt,
            include_dt_driver=args.dt_driver,
            include_hardware=args.hardware,
            memory_categories=memory_categories,
            memory_statuses=memory_statuses,
            scope_files=scope_files,
            mode_c=args.mode_c,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rules, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
