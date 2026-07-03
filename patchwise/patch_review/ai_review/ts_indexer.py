#!/usr/bin/env python3
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Container-side tree-sitter index daemon.

Protocol:

    host -> daemon: {"op": "lookup", "name": <str>, "limit": <int>}
    daemon -> host: {"candidates": [<entry>, ...]}

    host -> daemon: {"op": "constructs_in_file", "path": <kernel-relative str>}
    daemon -> host: {"constructs": [{"name","kind","start_line","end_line"}, ...]}

While building, `{"progress": <done>, "total": <n>}` lines stream on stdout; a
`{"ready": true, ...}` line is emitted once the index finishes, so the host
reads progress lines until `ready` before issuing requests.
"""
# TODO: Move this to a better place because Agent is the one using this now.
import json
import multiprocessing
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import tree_sitter_c
from tree_sitter import Language, Parser, Query, QueryCursor

SKIP_DIRS = {"Documentation"}
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

(declaration
  declarator: (init_declarator
    declarator: (identifier) @other.name
    value: (initializer_list))) @other.body
; static const struct file_operations foo_fops = { .read = ... };

(declaration
  declarator: (init_declarator
    declarator: (array_declarator declarator: (identifier) @other.name)
    value: (initializer_list))) @other.body
; static const struct of_device_id foo_match[] = { ... };

(declaration
  declarator: (init_declarator
    declarator: (pointer_declarator declarator: (identifier) @other.name)
    value: (initializer_list))) @other.body
; static struct attribute *foo_attrs[] = { ... };  (pointer form)
"""

_TS_QUERY = Query(_C_LANGUAGE, _TS_QUERY_SRC)

# Map a captured construct's grammar node type to the kind we report. The body
# capture is the whole construct node, so its type tells the kind apart (the
# query lumps all non-functions under @other.*). An aggregate initializer
# (`= { ... }`) — an ops table, id table, attribute group — is a `declaration`.
_KIND_BY_NODE = {
    "function_definition": "function",
    "struct_specifier": "struct",
    "union_specifier": "union",
    "enum_specifier": "enum",
    "type_definition": "typedef",
    "preproc_def": "macro",
    "preproc_function_def": "macro",
    "declaration": "initializer",
}

# Callees: the functions a given function body invokes. A direct call is
# `foo(...)` (function field is an identifier); an indirect call is
# `ops->fn(...)` or `obj.fn(...)` (function field is a field_expression) — the
# dominant call style in kernel code, which a semantic call-graph would miss.
_CALL_QUERY_SRC = """
(call_expression
  function: (identifier) @call.direct)

(call_expression
  function: (field_expression
    field: (field_identifier) @call.indirect))
"""

_CALL_QUERY = Query(_C_LANGUAGE, _CALL_QUERY_SRC)


def _callees_in_range(
    rel: str, start_line: int, end_line: int
) -> List[Dict[str, Any]]:
    """Return the calls made within [start_line, end_line] of file `rel`.

    Re-parses the one file on demand (tree-sitter is cheap) and runs the
    call-expression query, keeping captures whose call site falls inside the
    requested function-body range. Each entry is {name, line, kind} where kind
    is 'direct' (foo()) or 'indirect' (ops->fn()).
    """
    path = KERNEL / rel
    try:
        src = path.read_bytes()
    except OSError:
        return []
    parser = Parser(_C_LANGUAGE)
    tree = parser.parse(src)
    cursor = QueryCursor(_CALL_QUERY)
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for _, captures in cursor.matches(tree.root_node):
        for kind, key in (("direct", "call.direct"), ("indirect", "call.indirect")):
            for node in captures.get(key, []):
                row = node.start_point[0] + 1
                if not (start_line <= row <= end_line):
                    continue
                name = src[node.start_byte : node.end_byte].decode(
                    "utf-8", errors="replace"
                )
                if (name, row) in seen:
                    continue
                seen.add((name, row))
                out.append({"name": name, "line": row, "kind": kind})
    out.sort(key=lambda c: c["line"])
    return out


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
                    "kind": _KIND_BY_NODE.get(body_node.type, "other"),
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


def build_index(blocklist: Set[str]) -> Tuple[
    Dict[str, List[Dict[str, Any]]],
    Dict[str, List[Dict[str, Any]]],
    int,
    int,
]:
    """Return (by_name, constructs_by_file, files_parsed, files_skipped).

    ``blocklist`` holds workspace-relative directory paths to prune.

    constructs_by_file holds EVERY captured construct per file — functions,
    structs, unions, enums, typedefs, macros, and aggregate initializers — with
    its kind and line range, so a hit can be attributed to the innermost
    construct of any kind, not just functions.
    """
    files: List[str] = []
    for dirpath, dirnames, filenames in os.walk(KERNEL):
        rel = os.path.relpath(dirpath, KERNEL)
        # Prune dot-dirs, the always-skip basenames, and blocklisted paths.
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".")
            and d not in SKIP_DIRS
            and (d if rel == "." else f"{rel}/{d}") not in blocklist
        ]
        for fn in filenames:
            if not fn.startswith(".") and fn.endswith((".c", ".h")):
                files.append(os.path.join(dirpath, fn))
    total = len(files)
    print(f"ts-indexer: parsing {total} files", file=sys.stderr)

    by_name: Dict[str, List[Dict[str, Any]]] = {}
    constructs_by_file: Dict[str, List[Dict[str, Any]]] = {}
    skipped = 0

    # Stream progress ahead of the final `ready` line so the host can show it.
    done = 0
    step = max(1, min(total // 200, 2000))
    _write({"progress": 0, "total": total})
    with multiprocessing.Pool() as pool:
        for result in pool.imap_unordered(_parse_one, files, chunksize=32):
            done += 1
            if done % step == 0:
                _write({"progress": done, "total": total})
            if result is None:
                skipped += 1
                continue
            rel, captures = result
            file_constructs: List[Dict[str, Any]] = []
            for c in captures:
                entry = {"file": rel, **c}
                by_name.setdefault(entry["name"], []).append(entry)
                file_constructs.append(
                    {
                        "name": entry["name"],
                        "kind": entry["kind"],
                        "start_line": entry["start_line"],
                        "end_line": entry["end_line"],
                    }
                )
            if file_constructs:
                constructs_by_file[rel] = file_constructs

    return by_name, constructs_by_file, len(files) - skipped, skipped


def _write(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.write("\n")
    sys.stdout.flush()


def main() -> int:
    global KERNEL
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} <kernel-path> [blocked-dir ...]", file=sys.stderr)
        return 2
    KERNEL = Path(sys.argv[1]).resolve()
    if not KERNEL.is_dir():
        print(f"ts-indexer: kernel path not found: {KERNEL}", file=sys.stderr)
        return 1
    blocklist = set(sys.argv[2:])
    print(f"ts-indexer: kernel={KERNEL} blocklist={sorted(blocklist)}", file=sys.stderr)

    by_name, constructs_by_file, parsed, skipped = build_index(blocklist)
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
        elif op == "constructs_in_file":
            path = req.get("path", "")
            _write({"constructs": constructs_by_file.get(path, [])})
        elif op == "callees":
            path = req.get("path", "")
            start_line = int(req.get("start_line", 0))
            end_line = int(req.get("end_line", 0))
            _write({"callees": _callees_in_range(path, start_line, end_line)})
        elif op == "shutdown":
            break
        else:
            _write({"error": f"unknown op: {op}"})

    return 0


if __name__ == "__main__":
    sys.exit(main())
