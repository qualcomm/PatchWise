#!/usr/bin/env python3
"""Validate curated review memory entries."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ENTRY_RE = re.compile(r"^### (MEM-\d{4}): .+$", re.MULTILINE)
FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z -]*):\s*(.*)$")
VALID_STATUSES = {"draft", "active", "deprecated"}
VALID_CONFIDENCE = {"low", "medium", "high"}
STATUS_DIRS = ("active", "draft", "deprecated")
TOPIC_FILES = ("patch-scope.md", "commit-message.md", "dt-bindings.md", "subsystem-specific.md")
REQUIRED_FIELDS = [
    "Status",
    "Scope",
    "Triggers",
    "Maintainer evidence",
    "Review action",
    "False-positive guards",
    "Confidence",
    "Last updated",
]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def split_entries(memory_file: Path) -> list[tuple[str, str, int]]:
    content = memory_file.read_text(encoding="utf-8")
    matches = list(ENTRY_RE.finditer(content))
    entries: list[tuple[str, str, int]] = []

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        line_number = content.count("\n", 0, start) + 1
        entries.append((match.group(1), content[start:end].strip(), line_number))

    return entries


def parse_fields(entry_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}

    for line in entry_text.splitlines():
        match = FIELD_RE.match(line)
        if match:
            fields[match.group(1)] = match.group(2).strip()

    return fields


def entry_has_bullets(entry_text: str, field_name: str) -> bool:
    lines = entry_text.splitlines()

    for index, line in enumerate(lines):
        if line.startswith(f"{field_name}:"):
            for following_line in lines[index + 1 :]:
                if FIELD_RE.match(following_line) or following_line.startswith("### "):
                    return False
                if following_line.startswith("- "):
                    return True
            return False

    return False


def validate_entry(memory_file: Path, memory_id: str, entry_text: str, line_number: int) -> list[str]:
    errors: list[str] = []
    fields = parse_fields(entry_text)
    location = f"{memory_file}:{line_number}: {memory_id}"

    for field_name in REQUIRED_FIELDS:
        if field_name not in fields:
            errors.append(f"{location}: missing field '{field_name}'")

    status = fields.get("Status", "")
    if status and status not in VALID_STATUSES:
        errors.append(f"{location}: invalid Status '{status}'")

    confidence = fields.get("Confidence", "")
    if confidence and confidence not in VALID_CONFIDENCE:
        errors.append(f"{location}: invalid Confidence '{confidence}'")

    last_updated = fields.get("Last updated", "")
    if last_updated and not DATE_RE.match(last_updated):
        errors.append(f"{location}: Last updated must be YYYY-MM-DD")

    for bullet_field in ["Triggers", "Maintainer evidence", "Review action", "False-positive guards"]:
        if bullet_field in fields and not entry_has_bullets(entry_text, bullet_field):
            errors.append(f"{location}: '{bullet_field}' must include at least one bullet")

    entry_lines = entry_text.splitlines()
    if len(entry_lines) > 80:
        errors.append(f"{location}: entry is too long ({len(entry_lines)} lines, max 80)")

    if status == "active" and fields.get("False-positive guards") == "None":
        errors.append(f"{location}: active entries need real false-positive guards")

    return errors


def split_layout_exists(memory_dir: Path) -> bool:
    return any((memory_dir / status).is_dir() for status in STATUS_DIRS)


def discover_memory_files(memory_dir: Path) -> tuple[list[Path], list[str]]:
    errors: list[str] = []
    split_exists = split_layout_exists(memory_dir)
    flat_files = sorted(path for path in memory_dir.glob("*.md") if path.name != "index.md")

    if split_exists:
        files: list[Path] = []
        for status in STATUS_DIRS:
            status_dir = memory_dir / status
            if not status_dir.is_dir():
                errors.append(f"{status_dir}: missing split-layout status directory")
                continue
            for topic in TOPIC_FILES:
                topic_path = status_dir / topic
                if not topic_path.is_file():
                    errors.append(f"{topic_path}: missing split-layout topic file")
            for path in sorted(status_dir.glob("*.md")):
                if path.name not in TOPIC_FILES:
                    errors.append(f"{path}: unexpected memory topic filename")
                    continue
                files.append(path)
        if flat_files:
            errors.append(
                f"{memory_dir}: split layout is active; remove legacy flat topic files: "
                + ", ".join(path.name for path in flat_files)
            )
        return files, errors

    return flat_files, errors


def validate_memory(memory_dir: Path) -> tuple[list[str], int]:
    errors: list[str] = []
    entry_count = 0
    seen_ids: dict[str, Path] = {}

    if not memory_dir.exists():
        return [f"{memory_dir}: memory directory does not exist"], 0

    memory_files, discovery_errors = discover_memory_files(memory_dir)
    errors.extend(discovery_errors)
    if not memory_files:
        return [*errors, f"{memory_dir}: no memory topic files found"], 0

    for memory_file in memory_files:
        entries = split_entries(memory_file)
        entry_count += len(entries)
        expected_status = memory_file.parent.name if memory_file.parent.name in VALID_STATUSES else None

        for memory_id, entry_text, line_number in entries:
            fields = parse_fields(entry_text)
            status = fields.get("Status", "")
            if expected_status and status and status != expected_status:
                errors.append(
                    f"{memory_file}:{line_number}: {memory_id}: Status '{status}' does not match directory '{expected_status}'"
                )

            if memory_id in seen_ids:
                errors.append(
                    f"{memory_file}:{line_number}: duplicate {memory_id}; first seen in {seen_ids[memory_id]}"
                )
            else:
                seen_ids[memory_id] = memory_file

            errors.extend(validate_entry(memory_file, memory_id, entry_text, line_number))

    return errors, entry_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate review-commits memory entries")
    parser.add_argument(
        "memory_dir",
        nargs="?",
        default=Path(__file__).resolve().parents[1] / "refs" / "memory",
        type=Path,
        help="Path to refs/memory",
    )
    args = parser.parse_args()

    errors, entry_count = validate_memory(args.memory_dir)
    if errors:
        print("Memory lint failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Memory lint passed: {entry_count} entries checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
