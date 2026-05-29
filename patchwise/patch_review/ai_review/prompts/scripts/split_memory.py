#!/usr/bin/env python3
"""Split review memory topic files into active/draft/deprecated directories."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ENTRY_RE = re.compile(r"^### (MEM-\d{4}): (.+)$", re.MULTILINE)
FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z -]*):\s*(.*)$", re.MULTILINE)
STATUS_DIRS = ("active", "draft", "deprecated")
TOPIC_FILES = ("patch-scope.md", "commit-message.md", "dt-bindings.md", "subsystem-specific.md")


def strip_md_suffix(topic: str) -> str:
    return topic[:-3] if topic.endswith(".md") else topic


def split_entries(memory_file: Path) -> list[dict[str, object]]:
    content = memory_file.read_text(encoding="utf-8")
    matches = list(ENTRY_RE.finditer(content))
    entries: list[dict[str, object]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        text = content[start:end].strip()
        fields = {field: value.strip() for field, value in FIELD_RE.findall(text)}
        entries.append(
            {
                "id": match.group(1),
                "title": match.group(2),
                "topic": memory_file.name,
                "status": fields.get("Status", ""),
                "last_updated": fields.get("Last updated", ""),
                "text": text,
            }
        )
    return entries


def flat_topic_files(memory_dir: Path) -> list[Path]:
    return [memory_dir / name for name in TOPIC_FILES if (memory_dir / name).is_file()]


def split_topic_files(memory_dir: Path) -> list[Path]:
    files: list[Path] = []
    for status in STATUS_DIRS:
        for name in TOPIC_FILES:
            path = memory_dir / status / name
            if path.is_file():
                files.append(path)
    return files


def load_entries(memory_dir: Path) -> list[dict[str, object]]:
    sources = flat_topic_files(memory_dir) or split_topic_files(memory_dir)
    entries: list[dict[str, object]] = []
    for source in sources:
        topic = source.name
        for entry in split_entries(source):
            entry["topic"] = topic
            entries.append(entry)
    return entries


def validate_entries(entries: list[dict[str, object]]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, str] = {}
    for entry in entries:
        memory_id = str(entry["id"])
        topic = str(entry["topic"])
        status = str(entry["status"])
        if topic not in TOPIC_FILES:
            errors.append(f"{memory_id}: unknown topic file {topic}")
        if status not in STATUS_DIRS:
            errors.append(f"{memory_id}: missing or invalid Status '{status}'")
        if memory_id in seen:
            errors.append(f"{memory_id}: duplicate entry in {topic}; first seen in {seen[memory_id]}")
        seen[memory_id] = topic
    return errors


def header(status: str, topic: str) -> str:
    title = strip_md_suffix(topic).replace("-", " ").title()
    return f"# Review Memory — {title} ({status})\n\n"


def render_topic(status: str, topic: str, entries: list[dict[str, object]]) -> str:
    body = "\n\n".join(str(entry["text"]).strip() for entry in entries)
    if body:
        return header(status, topic) + body + "\n"
    return header(status, topic) + "No entries.\n"


def write_split(memory_dir: Path, entries: list[dict[str, object]]) -> None:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {
        (status, topic): [] for status in STATUS_DIRS for topic in TOPIC_FILES
    }
    for entry in entries:
        grouped[(str(entry["status"]), str(entry["topic"]))].append(entry)

    for status in STATUS_DIRS:
        (memory_dir / status).mkdir(parents=True, exist_ok=True)
        for topic in TOPIC_FILES:
            topic_entries = sorted(grouped[(status, topic)], key=lambda item: str(item["id"]))
            (memory_dir / status / topic).write_text(render_topic(status, topic, topic_entries), encoding="utf-8")

    for flat in flat_topic_files(memory_dir):
        flat.unlink()


def manifest(entries: list[dict[str, object]]) -> dict[str, object]:
    items = []
    for entry in sorted(entries, key=lambda item: str(item["id"])):
        text = str(entry["text"]).strip()
        status = str(entry["status"])
        topic = str(entry["topic"])
        items.append(
            {
                "id": entry["id"],
                "title": entry["title"],
                "topic": strip_md_suffix(topic),
                "status": status,
                "path": f"refs/memory/{status}/{topic}",
                "last_updated": entry["last_updated"],
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
    return {"entries": items}


def write_manifest(memory_dir: Path, entries: list[dict[str, object]]) -> None:
    (memory_dir / "manifest.json").write_text(
        json.dumps(manifest(entries), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Split refs/memory topic files by Status")
    parser.add_argument("--memory-dir", type=Path, default=Path(__file__).resolve().parents[1] / "refs" / "memory")
    parser.add_argument("--apply", action="store_true", help="Write split files and manifest")
    parser.add_argument("--check", action="store_true", help="Validate and print the split plan without writing")
    args = parser.parse_args(argv)

    if not args.memory_dir.is_dir():
        print(f"memory directory not found: {args.memory_dir}", file=sys.stderr)
        return 1

    entries = load_entries(args.memory_dir)
    errors = validate_entries(entries)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    counts: dict[str, int] = {status: 0 for status in STATUS_DIRS}
    for entry in entries:
        counts[str(entry["status"])] += 1
    print("memory split plan: " + ", ".join(f"{status}={counts[status]}" for status in STATUS_DIRS))

    if args.apply:
        before = {str(entry["id"]): hashlib.sha256(str(entry["text"]).strip().encode("utf-8")).hexdigest() for entry in entries}
        write_split(args.memory_dir, entries)
        after_entries = load_entries(args.memory_dir)
        after = {str(entry["id"]): hashlib.sha256(str(entry["text"]).strip().encode("utf-8")).hexdigest() for entry in after_entries}
        if before != after:
            print("entry content changed during split", file=sys.stderr)
            return 1
        write_manifest(args.memory_dir, after_entries)
        print(f"wrote split memory layout under {args.memory_dir}")
    elif not args.check:
        parser.error("choose --check or --apply")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
