#!/usr/bin/env python3
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Container-side tree-sitter index daemon.

Protocol:

    host -> daemon: {"op": "lookup", "name": <str>, "limit": <int>}
    daemon -> host: {"candidates": [<entry>, ...]}

    host -> daemon: {"op": "funcs_in_file", "path": <kernel-relative str>}
    daemon -> host: {"funcs": [{"name","start_line","end_line",...}, ...]}

A `{"ready": true, ...}` line is emitted once the index finishes building, so
the host can block on first stdout readline() before issuing requests.
"""
import json
import multiprocessing
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import tree_sitter_c
from tree_sitter import Language, Parser, Query, QueryCursor

SKIP_DIRS = {".git", "Documentation"}
KERNEL: Path

_C_LANGUAGE = Language(tree_sitter_c.language())

_TS_QUERY_SRC = """
(function_definition
  declarator: (function_declarator
    declarator: (identifier) @func.name)) @func.body
; int foo(int x) { ... }

(function_definition
  declarator: (pointer_declarator
    declarator: (function_declarator
      declarator: (identifier) @func.name))) @func.body
; struct page *foo(int x) { ... }

(function_definition
  declarator: (pointer_declarator
    declarator: (pointer_declarator
      declarator: (function_declarator
        declarator: (identifier) @func.name)))) @func.body
; char **foo(int x) { ... }

(struct_specifier
  name: (type_identifier) @other.name
  body: (field_declaration_list)) @other.body
; struct sk_buff { ... };

(union_specifier
  name: (type_identifier) @other.name
  body: (field_declaration_list)) @other.body
; union ktime { ... };

(enum_specifier
  name: (type_identifier) @other.name
  body: (enumerator_list)) @other.body
; enum pci_state { ... };

(type_definition   declarator: (type_identifier) @other.name) @other.body
; typedef unsigned long pgd_t;

(preproc_def       name: (identifier)       @other.name) @other.body
; #define PAGE_SIZE 4096

(preproc_function_def name: (identifier)    @other.name) @other.body
; #define list_for_each_entry(pos, head, member) ...
"""

_TS_QUERY = Query(_C_LANGUAGE, _TS_QUERY_SRC)


def _parse_one(path_str: str) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    """Parse one file in a worker. Returns (rel_path, capture_list) or None."""
    try:
        path = Path(path_str)
        src = path.read_bytes()
        parser = Parser(_C_LANGUAGE)
        tree = parser.parse(src)
        cursor = QueryCursor(_TS_QUERY)
        rel = str(path.relative_to(KERNEL))
        out: List[Dict[str, Any]] = []
        for _, captures in cursor.matches(tree.root_node):
            name_nodes = captures.get("func.name") or captures.get("other.name")
            body_nodes = captures.get("func.body") or captures.get("other.body")
            if not name_nodes or not body_nodes:
                continue
            name_node = name_nodes[0]
            body_node = body_nodes[0]
            try:
                name = src[name_node.start_byte : name_node.end_byte].decode(
                    "utf-8", errors="replace"
                )
            except Exception:
                continue
            out.append(
                {
                    "name": name,
                    "kind": "function" if "func.body" in captures else "other",
                    "start_line": body_node.start_point[0] + 1,
                    "end_line": body_node.end_point[0] + 1,
                    "name_line": name_node.start_point[0] + 1,
                    "name_col": name_node.start_point[1],
                }
            )
        return rel, out
    except Exception as e:
        print(f"ts-index skipped {path_str}: {e}", file=sys.stderr)
        return None


def build_index() -> Tuple[
    Dict[str, List[Dict[str, Any]]],
    Dict[str, List[Dict[str, Any]]],
    int,
    int,
]:
    """Return (by_name, funcs_by_file, files_parsed, files_skipped)."""
    files: List[str] = []
    for dirpath, dirnames, filenames in os.walk(KERNEL):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith((".c", ".h")):
                files.append(os.path.join(dirpath, fn))
    print(f"ts-indexer: parsing {len(files)} files", file=sys.stderr)

    by_name: Dict[str, List[Dict[str, Any]]] = {}
    funcs_by_file: Dict[str, List[Dict[str, Any]]] = {}
    skipped = 0

    with multiprocessing.Pool() as pool:
        for result in pool.imap_unordered(_parse_one, files, chunksize=32):
            if result is None:
                skipped += 1
                continue
            rel, captures = result
            file_funcs: List[Dict[str, Any]] = []
            for c in captures:
                entry = {"file": rel, **c}
                by_name.setdefault(entry["name"], []).append(entry)
                if entry["kind"] == "function":
                    file_funcs.append(
                        {
                            "name": entry["name"],
                            "start_line": entry["start_line"],
                            "end_line": entry["end_line"],
                        }
                    )
            if file_funcs:
                funcs_by_file[rel] = file_funcs

    return by_name, funcs_by_file, len(files) - skipped, skipped


def _write(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.write("\n")
    sys.stdout.flush()


def main() -> int:
    global KERNEL
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <kernel-path>", file=sys.stderr)
        return 2
    KERNEL = Path(sys.argv[1]).resolve()
    if not KERNEL.is_dir():
        print(f"ts-indexer: kernel path not found: {KERNEL}", file=sys.stderr)
        return 1
    print(f"ts-indexer: kernel={KERNEL}", file=sys.stderr)

    by_name, funcs_by_file, parsed, skipped = build_index()
    total_entries = sum(len(v) for v in by_name.values())
    _write(
        {
            "ready": True,
            "unique_names": len(by_name),
            "entries": total_entries,
            "files_parsed": parsed,
            "files_skipped": skipped,
        }
    )

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            _write({"error": f"bad json: {e}"})
            continue

        op = req.get("op")
        if op == "lookup":
            name = req.get("name", "")
            limit = int(req.get("limit", 100))
            candidates = by_name.get(name, [])
            _write({"candidates": candidates[:limit], "total": len(candidates)})
        elif op == "funcs_in_file":
            path = req.get("path", "")
            _write({"funcs": funcs_by_file.get(path, [])})
        elif op == "shutdown":
            break
        else:
            _write({"error": f"unknown op: {op}"})

    return 0


if __name__ == "__main__":
    sys.exit(main())
