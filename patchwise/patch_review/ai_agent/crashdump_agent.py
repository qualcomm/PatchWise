# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Agent specialization for root-cause analysis of kernel crashdumps.

`CrashdumpAgent` is a full kernel `Agent` (docker-backed kernel navigation) plus
crashdump-specific tools for reading the dump folder (`list_crash_files`,
`read_crash_file`, `search_crash`). The engineer therefore root-causes
from the crash artifacts AND grounds the fix in the real kernel source mounted in
the container.

The only differences from the base `Agent`:
  * `__init__` also binds a crashdump folder.
  * `_files_in_diff` returns empty (RCA analyzes a crash, not a patch).
  * `get_tools` / `dispatch_tool` add the crashdump tools on top of the base set.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from patchwise.docker import DockerManager
from patchwise.patch_review.ai_agent.agent import Agent


_READ_LINE_CAP = 400
_SEARCH_HIT_CAP = 200
_LIST_HIT_CAP = 100


# All paths are crashdump-relative, e.g. 'dmesg.log' or 'parser_output/cpu_ctx.txt'.
CRASHDUMP_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_crash_files",
            "description": (
                "List the artifacts in the crashdump folder. Use this first to "
                "see what evidence is available (dmesg, console logs, ramparser/"
                "ramdump-parser output, register and stack dumps, task lists, "
                "etc.). Result is {entries: [{name, type: 'file'|'dir', size}], "
                "total, truncated}; size is in bytes. Set recursive=true to walk "
                "subdirectories."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subdir": {
                        "type": "string",
                        "description": (
                            "Crashdump-relative subdirectory to list (use '.' or "
                            "omit for the top level)."
                        ),
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Whether to walk subdirectories (default false).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_crash_file",
            "description": (
                "Read lines [start, end] of a crashdump artifact (dmesg, a "
                "ramparser output file, a log). Capped at "
                f"{_READ_LINE_CAP} lines per call. When `truncated` is true, call "
                "again with a later `start` to read more. Returns {path, start, "
                "end, content, truncated, total_lines}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Crashdump-relative path, e.g. 'dmesg.log'.",
                    },
                    "start": {
                        "type": "integer",
                        "description": "1-based starting line (default 1).",
                    },
                    "end": {
                        "type": "integer",
                        "description": (
                            f"1-based ending line, inclusive (default start+{_READ_LINE_CAP - 1})."
                        ),
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_crash",
            "description": (
                "Search the crashdump artifacts for a regex pattern (Python "
                "regex). Use this to find a symbol, address, PID, error string, "
                "or signature across every text artifact at once. Each result is "
                "{path, line, snippet}. Capped at "
                f"{_SEARCH_HIT_CAP}; 'total' and 'truncated' flag overflow. Scope "
                "to one or more files/dirs with `file` (space/comma-separated) "
                "when you already know where to look."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Python regular expression to search for.",
                    },
                    "file": {
                        "type": "string",
                        "description": (
                            "Optional crashdump-relative file(s)/dir(s) to scope "
                            "the search (space/comma-separated). Searches every "
                            "text artifact when omitted."
                        ),
                    },
                },
                "required": ["pattern"],
            },
        },
    },
]

# Tool names handled here; everything else falls through to the base Agent.
_CRASHDUMP_TOOL_NAMES = {t["function"]["name"] for t in CRASHDUMP_TOOLS}


class CrashdumpAgent(Agent):
    """A full kernel `Agent` that also reads a crashdump folder."""

    def __init__(
        self,
        crashdump_dir: str,
        kernel_path: str,
        docker_manager: DockerManager,
        enable_edit_tools: bool = False,
    ):
        # Full kernel Agent over `kernel_path` (docker-backed navigation), so the
        # engineer has every navigation tool the code reviewer has.
        super().__init__(
            kernel_path=str(kernel_path),
            docker_manager=docker_manager,
            enable_edit_tools=enable_edit_tools,
        )
        self.crashdump_dir = Path(crashdump_dir).resolve()
        if not self.crashdump_dir.is_dir():
            raise NotADirectoryError(
                f"crashdump path is not a directory: {crashdump_dir}"
            )

    def _files_in_diff(self) -> Set[str]:
        # RCA analyzes a crash, not a patch — there is no diff to seed ranking.
        return set()

    # crashdump path safety

    def _abs_in_dump(self, rel: str) -> Path:
        """Resolve a crashdump-relative path under the dump dir, rejecting
        escapes. A leading './' or '/' is tolerated and normalized."""
        cleaned = (rel or "").strip().lstrip("/")
        if cleaned in ("", "."):
            return self.crashdump_dir
        target = (self.crashdump_dir / cleaned).resolve()
        base = self.crashdump_dir
        if target != base and base not in target.parents:
            raise ValueError(f"path escapes crashdump folder: {rel}")
        return target

    def _dump_rel(self, path: Path) -> str:
        """Crashdump-relative POSIX string for a resolved path."""
        try:
            return path.resolve().relative_to(self.crashdump_dir).as_posix()
        except ValueError:
            return path.name

    @staticmethod
    def _looks_binary(path: Path) -> bool:
        """Cheap text/binary probe: a NUL byte in the first 8 KiB means binary."""
        try:
            with open(path, "rb") as f:
                chunk = f.read(8192)
        except OSError:
            return True
        return b"\x00" in chunk

    def _text_files(self, roots: List[Path]) -> List[Path]:
        """Every readable, non-binary file under the given roots (files or dirs),
        sorted for determinism."""
        out: List[Path] = []
        for root in roots:
            if root.is_file():
                candidates = [root]
            elif root.is_dir():
                candidates = sorted(p for p in root.rglob("*") if p.is_file())
            else:
                continue
            for p in candidates:
                if any(part.startswith(".") for part in p.relative_to(self.crashdump_dir).parts):
                    continue
                if not self._looks_binary(p):
                    out.append(p)
        return out

    def _scope_roots(self, file: Optional[str]) -> List[Path]:
        """Parse a `file` argument (space/comma-separated) into validated roots;
        an empty argument means the whole crashdump folder."""
        if not file or not file.strip():
            return [self.crashdump_dir]
        roots: List[Path] = []
        for tok in (t for t in re.split(r"[,\s]+", file.strip()) if t):
            roots.append(self._abs_in_dump(tok))  # TODO: Some paths may be valid
        return roots

    # crashdump tools

    def _tool_list_crash_files(
        self, subdir: str = ".", recursive: bool = False
    ) -> Dict[str, Any]:
        try:
            base = self._abs_in_dump(subdir)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        if not base.is_dir():
            return {"ok": False, "error": f"not a directory: {subdir}"}

        walker = base.rglob("*") if recursive else base.iterdir()
        entries: List[Dict[str, Any]] = []
        for p in walker:
            if any(part.startswith(".") for part in p.relative_to(self.crashdump_dir).parts):
                continue
            try:
                size = p.stat().st_size if p.is_file() else 0
            except OSError:
                size = 0
            entries.append(
                {
                    "name": self._dump_rel(p) if recursive else p.name,
                    "type": "dir" if p.is_dir() else "file",
                    "size": size,
                }
            )
        entries.sort(key=lambda e: e["name"])
        total = len(entries)
        return {
            "ok": True,
            "result": {
                "entries": entries[:_LIST_HIT_CAP],
                "total": total,
                "truncated": total > _LIST_HIT_CAP,
            },
        }

    def _tool_read_crash_file(
        self, path: str, start: int = 1, end: Optional[int] = None
    ) -> Dict[str, Any]:
        try:
            target = self._abs_in_dump(path)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        if not target.is_file():
            return {"ok": False, "error": f"not a file: {path}"}

        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError as e:
            return {"ok": False, "error": f"could not read {path}: {e}"}

        total_lines = len(lines)
        start_1 = max(1, start)
        request_end = end if end is not None else start_1 + _READ_LINE_CAP - 1
        effective_end = min(request_end, start_1 + _READ_LINE_CAP - 1, total_lines)
        content = "".join(lines[start_1 - 1 : effective_end])
        return {
            "ok": True,
            "result": {
                "path": self._dump_rel(target),
                "start": start_1,
                "end": effective_end,
                "content": content,
                "truncated": effective_end < total_lines,
                "total_lines": total_lines,
            },
        }

    def _tool_search_crash(
        self, pattern: str, file: Optional[str] = None
    ) -> Dict[str, Any]:
        try:
            roots = self._scope_roots(file)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return {"ok": False, "error": f"invalid regex: {e}"}

        hits: List[Dict[str, Any]] = []
        total = 0
        for fpath in self._text_files(roots):
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for lineno, text in enumerate(f, 1):
                        if regex.search(text):
                            total += 1
                            if len(hits) < _SEARCH_HIT_CAP:
                                hits.append(
                                    {
                                        "path": self._dump_rel(fpath),
                                        "line": lineno,
                                        "snippet": text.strip()[:240],
                                    }
                                )
            except OSError:
                continue
        return {
            "ok": True,
            "result": hits,
            "total": total,
            "truncated": total > _SEARCH_HIT_CAP,
        }

    # tool surface + dispatch

    def get_tools(
        self, allowed: Optional[List[str]] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """Base kernel-navigation tools + the crashdump tools."""
        base = super().get_tools(None) or []
        combined = base + CRASHDUMP_TOOLS
        if allowed is None:
            return combined
        allowed_set = set(allowed)
        filtered = [
            t for t in combined if t.get("function", {}).get("name") in allowed_set
        ]
        return filtered or None

    def dispatch_tool(self, name: str, args: dict) -> dict:
        """Route the crashdump tools here; defer everything else to the base
        Agent (kernel navigation, git, record_*)."""
        crash_tools = {
            "list_crash_files": self._tool_list_crash_files,
            "read_crash_file": self._tool_read_crash_file,
            "search_crash": self._tool_search_crash,
        }
        tool_fn = crash_tools.get(name)
        if tool_fn is None:
            return super().dispatch_tool(name, args)
        try:
            result = tool_fn(**args)
        except TypeError as e:
            result = {"ok": False, "error": f"bad arguments for '{name}': {e}"}
        except Exception as e:
            self.logger.error(f"tool '{name}' raised: {e}")
            result = {"ok": False, "error": str(e)}
        self._log_tool_call(name, args, result)
        return result
