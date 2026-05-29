#!/usr/bin/env python3
"""Generate a deterministic per-patch evidence manifest for review-commits.

The manifest is intentionally compact: it records machine-derived facts and
artifact paths that the reviewer must use before writing a patch block.  The
HTML validator can later cross-check the block against this manifest instead of
trusting a prose `codebase_audit: DONE` assertion alone.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

SCHEMA = "review-commits.evidence-manifest.v1"
SOURCE_SUFFIXES = {".c", ".h", ".rs", ".S", ".s"}
DT_SUFFIXES = {".dts", ".dtsi", ".yaml", ".yml"}
BUILD_NAMES = {"Kconfig", "Kbuild", "Makefile"}
TOKEN_PATTERNS = {
    "runtime_pm": re.compile(r"\bpm_runtime_\w+\b"),
    "clock": re.compile(r"\bclk_\w+\b|\bdevm_clk_\w+\b"),
    "opp": re.compile(r"\bdev_pm_opp_\w+\b|\bOPP\b", re.IGNORECASE),
    "icc": re.compile(r"\bicc_\w+\b|\bgeni_icc_\w+\b"),
    "dma": re.compile(r"\bdma\w*\b|\bdmaengine_\w+\b", re.IGNORECASE),
    "irq": re.compile(r"\birq\w*\b|\brequest_irq\b", re.IGNORECASE),
    "match_data": re.compile(r"\b(?:device_get_match_data|of_device_get_match_data)\b"),
    "resource_helper": re.compile(r"\b\w*(?:resources?|init|setup|prepare|acquire)\w*\s*\("),
}
FUNC_DEF_RE = re.compile(
    r"^[A-Za-z_][\w\s\*]*\s+(?P<name>[A-Za-z_][\w]*)\s*\([^;]*\)\s*\{",
    re.MULTILINE,
)
CALL_RE = re.compile(r"\b(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(")
HUNK_RE = re.compile(r"^@@[^@]*@@\s*(?P<context>.*)$")
DIFF_GIT_RE = re.compile(r"^diff --git a/(?P<old>.+?) b/(?P<new>.+)$")
REF_RE = re.compile(r"\$ref:\s*(?:/schemas/)?(?P<ref>[^#\s]+)")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def normalize_path(path: str) -> str:
    path = path.strip()
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path


def parse_patch_files(patch_text: str) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for line in patch_text.splitlines():
        match = DIFF_GIT_RE.match(line)
        if not match:
            continue
        for key in ("old", "new"):
            path = normalize_path(match.group(key))
            if path == "/dev/null" or path in seen:
                continue
            seen.add(path)
            files.append(path)
    return files


def changed_lines(patch_text: str) -> str:
    lines: list[str] = []
    for line in patch_text.splitlines():
        if not line or line[0] not in {"+", "-"}:
            continue
        if line.startswith(("+++", "---")):
            continue
        lines.append(line[1:])
    return "\n".join(lines)


def changed_functions(patch_text: str) -> list[str]:
    functions: list[str] = []
    seen: set[str] = set()
    for line in patch_text.splitlines():
        match = HUNK_RE.match(line)
        if not match:
            continue
        context = match.group("context").strip()
        if not context:
            continue
        name_match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", context)
        if name_match:
            name = name_match.group(1)
            if name not in seen:
                seen.add(name)
                functions.append(name)
    return functions


def token_summary(text: str) -> dict[str, int]:
    return {name: len(pattern.findall(text)) for name, pattern in TOKEN_PATTERNS.items()}


def source_file(path: str) -> bool:
    return Path(path).suffix in SOURCE_SUFFIXES


def dt_file(path: str) -> bool:
    path_obj = Path(path)
    return (
        path.startswith("Documentation/devicetree/bindings/")
        or path_obj.suffix in DT_SUFFIXES
    )


def build_file(path: str) -> bool:
    return Path(path).name in BUILD_NAMES


def required_read(path: str, reason: str) -> dict[str, str | bool]:
    return {"path": path, "reason": reason, "required": True}


def source_root_file(source_root: Path | None, relpath: str) -> Path | None:
    if source_root is None:
        return None
    candidate = source_root / relpath
    return candidate if candidate.is_file() else None


def yaml_refs(source_root: Path | None, relpaths: Iterable[str]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    if source_root is None:
        return refs
    for relpath in relpaths:
        if Path(relpath).suffix not in {".yaml", ".yml"}:
            continue
        path = source_root_file(source_root, relpath)
        if path is None:
            continue
        for match in REF_RE.finditer(read_text(path)):
            ref = match.group("ref").strip()
            if not ref.startswith("Documentation/"):
                ref = f"Documentation/devicetree/bindings/{ref}"
            if ref not in seen and (source_root / ref).exists():
                seen.add(ref)
                refs.append(ref)
    return refs


def helper_candidates(patch_text: str) -> list[str]:
    helpers: list[str] = []
    seen: set[str] = set()
    for line in changed_lines(patch_text).splitlines():
        if not line:
            continue
        for match in CALL_RE.finditer(line):
            name = match.group("name")
            if name in {"if", "for", "while", "switch", "return", "sizeof"}:
                continue
            if not re.search(r"(?:init|setup|prepare|activate|deactivate|set_rate|resource|helper)", name):
                continue
            if name not in seen:
                seen.add(name)
                helpers.append(name)
    return helpers


def find_helper_defs(source_root: Path | None, files: Iterable[str], helpers: Iterable[str]) -> list[str]:
    if source_root is None:
        return []
    helper_set = set(helpers)
    if not helper_set:
        return []
    found: list[str] = []
    seen: set[str] = set()
    search_dirs = {str(Path(path).parent) for path in files if source_file(path)}
    for directory in sorted(search_dirs):
        root = source_root / directory
        if not root.is_dir():
            continue
        for path in root.glob("*.c"):
            try:
                text = read_text(path)
            except OSError:
                continue
            for match in FUNC_DEF_RE.finditer(text):
                if match.group("name") in helper_set:
                    relpath = str(path.relative_to(source_root))
                    if relpath not in seen:
                        seen.add(relpath)
                        found.append(relpath)
    return found


def build_manifest(
    patch_file: Path,
    patch_number: int,
    output: Path,
    source_root: Path | None,
) -> dict[str, object]:
    patch_text = read_text(patch_file)
    files = parse_patch_files(patch_text)
    changed = changed_lines(patch_text)
    source_files = [path for path in files if source_file(path)]
    dt_files = [path for path in files if dt_file(path)]
    build_files = [path for path in files if build_file(path)]
    functions = changed_functions(patch_text)
    helpers = helper_candidates(patch_text)
    helper_def_files = find_helper_defs(source_root, files, helpers)
    wrapper_schema_files = yaml_refs(source_root, dt_files)

    reads: list[dict[str, str | bool]] = []
    seen_reads: set[str] = set()
    for relpath, reason in [
        *[(path, "touched_source") for path in source_files],
        *[(path, "dt_binding") for path in dt_files],
        *[(path, "build_descriptor") for path in build_files],
        *[(path, "helper_definition") for path in helper_def_files],
        *[(path, "referenced_schema") for path in wrapper_schema_files],
    ]:
        if relpath in seen_reads:
            continue
        seen_reads.add(relpath)
        reads.append(required_read(relpath, reason))

    return {
        "schema": SCHEMA,
        "patch_number": patch_number,
        "patch_file": str(patch_file),
        "source_root": str(source_root) if source_root else "",
        "output": str(output),
        "changed_files": files,
        "changed_source_files": source_files,
        "changed_dt_files": dt_files,
        "changed_build_files": build_files,
        "changed_functions": functions,
        "helper_candidates": helpers,
        "required_reads": reads,
        "tokens": token_summary(changed),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch-file", type=Path, required=True)
    parser.add_argument("--patch-number", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if not args.patch_file.is_file():
        print(f"missing patch file: {args.patch_file}", file=sys.stderr)
        return 2
    if args.patch_number < 1:
        print("--patch-number must be >= 1", file=sys.stderr)
        return 2
    if args.source_root is not None and not args.source_root.is_dir():
        print(f"missing source root: {args.source_root}", file=sys.stderr)
        return 2
    manifest = build_manifest(args.patch_file, args.patch_number, args.output, args.source_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"evidence manifest written: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
