#!/usr/bin/env python3
"""Resolve concrete DTB make targets for touched DTS/DTSI files.

Given a patch diff, emit one make target per line suitable for:

    make CHECK_DTBS=1 <target>.dtb

This narrows DT validation to the DTBs directly affected by the patch instead
of running a full-tree ``dtbs_check``.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict, deque
from pathlib import Path

_DIFF_HEADER_RE = re.compile(r"^\+\+\+ b/(.+)$")
_INCLUDE_RE = re.compile(r'^\s*(?:#include|/include/)\s+"([^"]+)"')
_DTB_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_./+-])([A-Za-z0-9_./+-]+\.dtb)\b")


def _parse_changed_paths(patch_file: Path) -> list[Path]:
    changed: list[Path] = []
    seen: set[Path] = set()

    for line in patch_file.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _DIFF_HEADER_RE.match(line)
        if not match:
            continue
        path = match.group(1).strip()
        if path == "/dev/null":
            continue
        rel = Path(path)
        if rel not in seen:
            seen.add(rel)
            changed.append(rel)
    return changed


def _is_dt_source(path: Path) -> bool:
    parts = path.parts
    return (
        len(parts) >= 5
        and parts[0] == "arch"
        and parts[2] == "boot"
        and parts[3] == "dts"
        and path.suffix in {".dts", ".dtsi"}
    )


def _dts_root(path: Path) -> Path:
    return Path(*path.parts[:4])


def _resolve_include(src: Path, include: str, dts_root: Path, project: Path) -> Path | None:
    include_path = Path(include)
    candidates = [
        (project / src.parent / include_path),
        (project / dts_root / include_path),
    ]
    for candidate in candidates:
        if candidate.suffix not in {".dts", ".dtsi"}:
            continue
        if candidate.exists():
            return candidate.resolve()
    return None


def _build_reverse_include_graph(project: Path, dts_root: Path) -> dict[Path, set[Path]]:
    reverse_graph: dict[Path, set[Path]] = defaultdict(set)
    sources = sorted((project / dts_root).rglob("*.dts")) + sorted((project / dts_root).rglob("*.dtsi"))

    for source in sources:
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            match = _INCLUDE_RE.match(line)
            if not match:
                continue
            target = _resolve_include(source.relative_to(project), match.group(1), dts_root, project)
            if target is None:
                continue
            reverse_graph[target].add(source.resolve())
    return reverse_graph


def _declared_dtb_targets(project: Path, dts_root: Path) -> set[str]:
    """Return DTB targets actually declared by Makefiles under this DTS tree."""

    declared: set[str] = set()
    root = project / dts_root
    for makefile in sorted(root.rglob("Makefile")):
        try:
            text = makefile.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        makefile_dir = makefile.parent.relative_to(project)
        for token in _DTB_TOKEN_RE.findall(text):
            declared.add((makefile_dir / token).as_posix())
    return declared


def _collect_consumer_dts(start: Path, reverse_graph: dict[Path, set[Path]]) -> set[Path]:
    consumers: set[Path] = set()
    queue: deque[Path] = deque([start])
    seen: set[Path] = {start}

    while queue:
        current = queue.popleft()
        for parent in reverse_graph.get(current, set()):
            if parent in seen:
                continue
            seen.add(parent)
            if parent.suffix == ".dts":
                consumers.add(parent)
            else:
                queue.append(parent)
    return consumers


def resolve_targets(project: Path, patch_file: Path) -> list[str]:
    changed = [path for path in _parse_changed_paths(patch_file) if _is_dt_source(path)]
    if not changed:
        return []

    targets: set[str] = set()
    reverse_graph_cache: dict[Path, dict[Path, set[Path]]] = {}
    declared_targets_cache: dict[Path, set[str]] = {}

    for rel_path in changed:
        abs_path = (project / rel_path).resolve()
        dts_root = _dts_root(rel_path)
        declared_targets = declared_targets_cache.setdefault(
            dts_root,
            _declared_dtb_targets(project, dts_root),
        )
        if rel_path.suffix == ".dts":
            candidate = rel_path.with_suffix(".dtb").as_posix()
            if candidate in declared_targets:
                targets.add(candidate)
            continue

        reverse_graph = reverse_graph_cache.setdefault(
            dts_root,
            _build_reverse_include_graph(project, dts_root),
        )
        for consumer in _collect_consumer_dts(abs_path, reverse_graph):
            candidate = consumer.relative_to(project).with_suffix(".dtb").as_posix()
            if candidate in declared_targets:
                targets.add(candidate)

    return sorted(targets)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True, help="Kernel tree root")
    parser.add_argument("--patch-file", type=Path, required=True, help="Patch diff file to inspect")
    args = parser.parse_args(argv)

    project = args.project.resolve()
    patch_file = args.patch_file.resolve()
    if not patch_file.is_file():
        print(f"missing patch file: {patch_file}", file=sys.stderr)
        return 1

    for target in resolve_targets(project, patch_file):
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
