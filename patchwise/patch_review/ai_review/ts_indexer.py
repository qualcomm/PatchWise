# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Host-side tree-sitter parse module and index orchestrator.

`parse_constructs`, `confirm_definitions`, `callees_in_range` -- pure functions
on bytes, no I/O.

`TsIndex` -- orchestrates blob resolution, the Redis cache, and rg candidate
search against a live review container.  The Agent constructs one and calls
through it; all git/rg/cache/parse logic stays here.
"""

import io
import logging
import subprocess
import tarfile
from typing import Any, Dict, List, Tuple

import tree_sitter_c
from tree_sitter import Language, Parser, Query, QueryCursor

from patchwise import PACKAGE_NAME
from patchwise.patch_review.ai_review.ts_cache import TsCache

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

_CALL_QUERY_SRC = """
(call_expression
  function: (identifier) @call.direct)

(call_expression
  function: (field_expression
    field: (field_identifier) @call.indirect))
"""

_CALL_QUERY = Query(_C_LANGUAGE, _CALL_QUERY_SRC)


# ---------------------------------------------------------------------------
# Pure parse functions
# ---------------------------------------------------------------------------


def parse_constructs(src: bytes) -> List[Dict[str, Any]]:
    """Return tree-sitter constructs for raw C source bytes.

    Each entry: {name, kind, start_line, end_line, name_line, name_col}.
    No 'file' key -- the caller attributes results to their file.
    """
    parser = Parser(_C_LANGUAGE)
    tree = parser.parse(src)
    cursor = QueryCursor(_TS_QUERY)
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
    return out


def confirm_definitions(
    name: str, per_file: Dict[str, List[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    """Return entries that define `name`, attributed to their file.

    `per_file` maps kernel-relative path to parse_constructs() output.
    Returns entries in the find_definition shape:
    {file, name, kind, start_line, end_line, name_line, name_col}.
    """
    out = []
    for file_path, constructs in per_file.items():
        for c in constructs:
            if c.get("name") == name:
                out.append({"file": file_path, **c})
    return out


def callees_in_range(
    src: bytes, start_line: int, end_line: int
) -> List[Dict[str, Any]]:
    """Return calls made within [start_line, end_line] of C source bytes.

    Each entry: {name, line, kind} where kind is 'direct' or 'indirect'.
    """
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


# ---------------------------------------------------------------------------
# TsIndex -- orchestrates blob resolution, Redis cache, and rg search
# ---------------------------------------------------------------------------


class TsIndex:
    """Host-side tree-sitter index for one review container.

    Owns blob resolution, the Redis cache, and rg candidate lookup.
    Counters `cached` / `parsed` accumulate over the review lifetime.
    """

    def __init__(
        self, docker_manager: Any, cache: TsCache, blocklist: List[str]
    ) -> None:
        self._dm = docker_manager
        self._cache = cache
        self._blocklist = blocklist
        self._kernel_dir = docker_manager.kernel_dir
        self.cached: int = 0
        self.parsed: int = 0
        self._logger = logging.getLogger(f"{PACKAGE_NAME}.tsindex")

    # -- working-tree files --
    # Callers pass paths `rg` just reported, so every path is a readable file.

    def _hash_files(self, rels: List[str]) -> Dict[str, str]:
        """Map each rel to its working-tree blob SHA in one exec."""
        if not rels:
            return {}
        proc = self._dm.run_command(
            ["git", "hash-object", "--no-filters", "--stdin-paths"],
            cwd=str(self._kernel_dir),
            stdin=subprocess.PIPE,
        )
        out, err = proc.communicate(input="\n".join(rels) + "\n")
        shas = out.splitlines()
        if proc.returncode or len(shas) != len(rels):
            raise RuntimeError(f"git hash-object failed: {err}")
        return dict(zip(rels, shas))

    def _read_files(self, rels: List[str]) -> Dict[str, bytes]:
        """Read working-tree bytes for many paths in one exec, as a tar stream
        (paths fed NUL-separated on stdin, so no ARG_MAX limit)."""
        rels = list(dict.fromkeys(rels))
        if not rels:
            return {}
        proc = self._dm.run_command(
            ["tar", "-cf", "-", "--null", "-T", "-"],
            cwd=str(self._kernel_dir),
            text=False,
            stdin=subprocess.PIPE,
        )
        raw, err = proc.communicate(input=b"\0".join(r.encode() for r in rels))
        if proc.returncode:
            raise RuntimeError(f"tar of {len(rels)} files failed: {err!r}")
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
            return {m.name: tar.extractfile(m).read() for m in tar if m.isfile()}

    # -- cache-backed parse --

    def _constructs_for_paths(self, rels: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Resolve+parse many paths with a fixed number of docker execs.

        One `git hash-object` exec, one `cache.mget`, then -- only if anything
        missed -- one `tar` exec for the misses' bytes and one `cache.mset` for
        their parses. Returns {rel: constructs} for every rel.
        """
        sha_by_rel = self._hash_files(list(dict.fromkeys(rels)))
        cached_map = self._cache.mget(list(dict.fromkeys(sha_by_rel.values())))
        self.cached += sum(1 for v in cached_map.values() if v is not None)

        # One representative path per distinct missing SHA, so identical-content
        # files are read and parsed once.
        rel_by_miss = {
            sha: rel for rel, sha in sha_by_rel.items() if cached_map.get(sha) is None
        }
        bytes_by_rel = self._read_files(list(rel_by_miss.values()))
        parsed = {
            sha: parse_constructs(bytes_by_rel[rel]) for sha, rel in rel_by_miss.items()
        }
        self._cache.mset(parsed)
        self.parsed += len(parsed)
        cached_map.update(parsed)

        return {rel: cached_map.get(sha) or [] for rel, sha in sha_by_rel.items()}

    # -- public query methods --

    def lookup(self, name: str) -> List[Dict[str, Any]]:
        """Return every index entry defining `name` via rg + cache + tree-sitter.

        Returns all confirmed definers unranked; the caller ranks by proximity
        and applies its own display cap. Truncating here (before ranking) could
        drop the nearest-to-the-change definer for a heavily-redefined name.
        """
        rg_cmd = [
            "rg",
            "--files-with-matches",
            "--word-regexp",
            "--glob",
            "*.c",
            "--glob",
            "*.h",
        ]
        for entry in self._blocklist:
            rg_cmd += ["--glob", f"!{entry}"]
        rg_cmd += [name, str(self._kernel_dir)]
        proc = self._dm.run_command(rg_cmd, cwd=None)
        out, _ = proc.communicate()

        kernel_prefix = str(self._kernel_dir) + "/"
        candidate_rels = []
        for line in (out or "").splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith(kernel_prefix):
                line = line[len(kernel_prefix) :]
            candidate_rels.append(line)

        if len(candidate_rels) > 200:
            self._logger.warning(
                f"ts_lookup({name!r}): {len(candidate_rels)} candidate files -- "
                "large lookup; results are still complete"
            )

        per_file = self._constructs_for_paths(candidate_rels)
        return confirm_definitions(name, per_file)

    def constructs_in_files(self, rels: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Return {rel: [{name, kind, start_line, end_line}]} for many paths.

        One blob-resolution + cache/parse pass for the whole set (see
        `_constructs_for_paths`), not a git exec per file.
        """
        per_file = self._constructs_for_paths(rels)
        return {
            rel: [
                {
                    "name": c["name"],
                    "kind": c["kind"],
                    "start_line": c["start_line"],
                    "end_line": c["end_line"],
                }
                for c in constructs
            ]
            for rel, constructs in per_file.items()
        }

    def callees_batch(
        self, specs: List[Tuple[str, int, int]]
    ) -> List[List[Dict[str, Any]]]:
        """Return callees for each (rel, start_line, end_line) spec."""
        blob_bytes = self._read_files([rel for rel, _, _ in specs])
        out: List[List[Dict[str, Any]]] = []
        for rel, start_line, end_line in specs:
            raw = blob_bytes.get(rel, b"")
            out.append(callees_in_range(raw, start_line, end_line))
        return out
