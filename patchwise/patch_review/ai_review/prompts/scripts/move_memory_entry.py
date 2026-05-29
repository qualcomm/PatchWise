#!/usr/bin/env python3
"""Move a split-layout memory entry to a new lifecycle status."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ENTRY_RE = re.compile(r"^### (MEM-\d{4}): .+$", re.MULTILINE)
STATUS_RE = re.compile(r"(?m)^Status:\s*(active|draft|deprecated)\s*$")
VALID_STATUSES = {"active", "draft", "deprecated"}
TOPIC_FILES = ("patch-scope.md", "commit-message.md", "dt-bindings.md", "subsystem-specific.md")


def split_entries(path: Path) -> list[tuple[str, str]]:
    content = path.read_text(encoding="utf-8")
    matches = list(ENTRY_RE.finditer(content))
    entries: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        entries.append((match.group(1), content[start:end].strip()))
    return entries


def render_file(path: Path, status: str, topic: str, entries: list[str]) -> None:
    title = (topic[:-3] if topic.endswith(".md") else topic).replace("-", " ").title()
    header = f"# Review Memory — {title} ({status})\n\n"
    body = "\n\n".join(entry.strip() for entry in entries)
    path.write_text(header + (body + "\n" if body else "No entries.\n"), encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Move a memory entry between active/draft/deprecated files")
    parser.add_argument("memory_id", help="MEM-#### ID to move")
    parser.add_argument("--status", required=True, choices=sorted(VALID_STATUSES), help="Target status")
    parser.add_argument("--memory-dir", type=Path, default=Path(__file__).resolve().parents[1] / "refs" / "memory")
    args = parser.parse_args(argv)

    memory_dir = args.memory_dir
    found: tuple[Path, str] | None = None
    for status in VALID_STATUSES:
        for topic in TOPIC_FILES:
            path = memory_dir / status / topic
            if not path.is_file():
                continue
            for memory_id, entry in split_entries(path):
                if memory_id == args.memory_id:
                    if found is not None:
                        print(f"duplicate {args.memory_id} found", file=sys.stderr)
                        return 1
                    found = (path, entry)

    if found is None:
        print(f"{args.memory_id} not found in split memory layout", file=sys.stderr)
        return 1

    source_path, entry = found
    topic = source_path.name
    source_status = source_path.parent.name
    target_path = memory_dir / args.status / topic

    if source_status == args.status:
        print(f"{args.memory_id} is already in {args.status}/{topic}")
        return 0

    entry = STATUS_RE.sub(f"Status: {args.status}", entry, count=1)

    source_entries = [text for memory_id, text in split_entries(source_path) if memory_id != args.memory_id]
    target_entries = [text for _memory_id, text in split_entries(target_path)] if target_path.exists() else []
    target_entries.append(entry)
    target_entries.sort(key=lambda text: ENTRY_RE.search(text).group(1) if ENTRY_RE.search(text) else text)

    render_file(source_path, source_status, topic, source_entries)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    render_file(target_path, args.status, topic, target_entries)

    lint = subprocess.run([sys.executable, str(Path(__file__).with_name("memory_lint.py")), str(memory_dir)], text=True)
    if lint.returncode != 0:
        return lint.returncode
    split = subprocess.run([sys.executable, str(Path(__file__).with_name("split_memory.py")), "--memory-dir", str(memory_dir), "--apply"], text=True)
    if split.returncode != 0:
        return split.returncode

    print(f"moved {args.memory_id} to {args.status}/{topic}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
