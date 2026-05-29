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
DT_BINDING_HEADER_RE = re.compile(r"(^|/)include/dt-bindings/.+\.h$")
DT_SUFFIXES = {".dts", ".dtsi"}
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
MATCH_DATA_ASSIGN_RE = re.compile(
    r"(?:[\w\s\*]+?\s+)?(?P<expr>\w+(?:->\w+)*)\s*=\s*"
    r"(?P<api>device_get_match_data|of_device_get_match_data)\s*\("
)
PM_RUNTIME_GET_SYNC_RE = re.compile(r"\bpm_runtime_get_sync\s*\(")
PM_RUNTIME_API_RE = re.compile(r"\bpm_runtime_[A-Za-z0-9_]+\s*\(")
BARE_PM_RUNTIME_GET_SYNC_RE = re.compile(r"^\s*pm_runtime_get_sync\s*\([^;]+\);", re.MULTILINE)
COMPATIBLE_STRING_RE = re.compile(
    r"compatible\s*=\s*\"(?P<dts>[^\"]+)\"|"
    r"const:\s*[\"']?(?P<const>[A-Za-z0-9_.+-]+,[A-Za-z0-9_.+-]+)[\"']?"
)
RESOURCE_ABSTRACTION_RE = re.compile(
    r"(?:\(\*\s*\w*(?:rate|clk|clock|opp|perf|power|resource|bw)\w*\s*\)|"
    r"\.\s*\w*(?:rate|clk|clock|opp|perf|power|resource|bw)\w*\s*=|"
    r"->\s*\w*(?:rate|clk|clock|opp|perf|power|resource|bw)\w*\s*\()",
    re.IGNORECASE,
)
LOCAL_DECL_RE = re.compile(
    r"^\s*(?!return\b)(?:"
    r"(?:const\s+)?(?:struct|union|enum)\s+[A-Za-z_][A-Za-z0-9_]*\s+"
    r"|(?:const\s+)?(?:unsigned|signed|long|short)\s+"
    r"|(?:const\s+)?(?:bool|char|int|u8|u16|u32|u64|s8|s16|s32|s64|size_t|ssize_t|"
    r"dma_addr_t|phys_addr_t|gfp_t|irqreturn_t|ktime_t|[A-Za-z_][A-Za-z0-9_]*_t)\s+"
    r"|(?:const\s+)?[A-Za-z_][A-Za-z0-9_]*\s+\*+\s*"
    r")(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*\[[^\]]*\])?\s*(?:[=;,)]|$)"
)
ESCAPED_LOCAL_FIELD_STORE_RE = re.compile(
    r"(?P<target>[A-Za-z_][A-Za-z0-9_]*->[A-Za-z_][A-Za-z0-9_]*)\s*=\s*&(?P<local>[A-Za-z_][A-Za-z0-9_]*)\b"
)
ESCAPED_LOCAL_API_STORE_RE = re.compile(
    r"\b(?P<api>(?:platform_set_drvdata|dev_set_drvdata|pci_set_drvdata|spi_set_drvdata|"
    r"i2c_set_clientdata|video_set_drvdata|snd_soc_component_set_drvdata|"
    r"snd_soc_dai_set_drvdata|usb_set_intfdata))\s*\([^,]+,\s*&(?P<local>[A-Za-z_][A-Za-z0-9_]*)\s*\)"
)
# Catches &local_var passed as any argument to any function not already handled
# by ESCAPED_LOCAL_FIELD_STORE_RE or ESCAPED_LOCAL_API_STORE_RE.  The
# _local_declaration gate in lifetime_facts() rejects function parameters,
# globals, and statics — only locals declared within the patch hunk fire.
# Limited to scalar-type locals (u8/u16/u32/u64/int/etc.) to avoid false
# positives for struct types that are legitimately operated on by address
# (mutex_lock, list_add, etc.).  This covers custom create/register helpers
# (e.g. iris_vpu_bus_create_device) that store a caller-provided pointer in
# platform_data or similar fields.
ESCAPED_LOCAL_GENERIC_CALL_RE = re.compile(
    r"\b(?P<api>[A-Za-z_][A-Za-z0-9_]*)\s*\([^;]*&(?P<local>[A-Za-z_][A-Za-z0-9_]*)\b[^;]*\)"
)
_SCALAR_DECL_RE = re.compile(
    r"^\s*(?:const\s+)?(?:unsigned\s+|signed\s+|long\s+|short\s+)?"
    r"(?:bool|char|int|u8|u16|u32|u64|s8|s16|s32|s64|__u8|__u16|__u32|__u64|"
    r"size_t|ssize_t|dma_addr_t|phys_addr_t|gfp_t|irqreturn_t|ktime_t|"
    r"[A-Za-z_][A-Za-z0-9_]*_t)\s+(?!\*)"
)
SETUP_RESULT_ASSIGN_RE = re.compile(
    r"^\s*(?P<status>ret|rc|err|error)\s*=\s*(?P<helper>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.IGNORECASE,
)
SETUP_HELPER_NAME_RE = re.compile(
    r"(?:init|setup|prepare|enable|start|acquire|alloc|configure|config|parse|resume|activate)",
    re.IGNORECASE,
)
PUBLISH_CALL_RE = re.compile(
    r"\b(?P<call>(?:\w*(?:register|publish|attach|bind|expose)\w*|list_add(?:_tail)?|"
    r"device_add|component_add|cdev_device_add|misc_register|sysfs_create(?:_group|_link)?))\s*\("
)
TEARDOWN_CALL_RE = re.compile(
    r"\b(?P<call>\w*(?:shutdown|unregister|release|disable|free|put|stop|cleanup)\w*)\s*\(",
    re.IGNORECASE,
)
DIMENSION_PAIRS = (
    ("width", "height"),
    ("input", "output"),
    ("rx", "tx"),
    ("read", "write"),
    ("src", "dst"),
    ("source", "sink"),
    ("row", "col"),
    ("rows", "cols"),
)
CAPACITY_GUARD_RE = re.compile(
    r"\b(?:if|while)\s*\(|[<>]=?|==|!=|\b(?:max|min|limit|cap|capacity|count|num|size|len)\b",
    re.IGNORECASE,
)
STATE_FIELD_ASSIGN_RE = re.compile(
    r"^\s*(?P<target>[A-Za-z_][A-Za-z0-9_]*(?:->|\.)"
    r"[A-Za-z_][A-Za-z0-9_]*(?:state|status|started|enabled|active|loaded|load|"
    r"count|vote|rate|cached|valid)[A-Za-z0-9_]*)\s*=\s*(?P<value>[^;]+);",
    re.IGNORECASE,
)
STATE_SUCCESS_VALUE_RE = re.compile(
    r"\b(?:true|1|STARTED|ENABLED|ACTIVE|LOADED|ON|RUNNING|PREPARED|VALID)\b|"
    r"\b[A-Za-z_][A-Za-z0-9_]*(?:STARTED|ENABLED|ACTIVE|LOADED|ON|RUNNING|PREPARED|VALID)\b",
    re.IGNORECASE,
)
START_RESULT_ASSIGN_RE = re.compile(
    r"^\s*(?P<status>ret|rc|err|error)\s*=\s*(?P<operation>[A-Za-z_][A-Za-z0-9_]*"
    r"(?:start|resume|enable|load|boot|power_on|activate)[A-Za-z0-9_]*)\s*\(",
    re.IGNORECASE,
)
RESOURCE_GET_REMOVED_RE = re.compile(
    r"^\s*(?:devm_)?(?P<resource>[A-Za-z][A-Za-z0-9]*)_get\s*\("
)
RESOURCE_GET_GUARD_EXCLUSIONS = {"device", "dev", "fwnode", "of", "platform", "pm_runtime"}
SETTER_ASSIGN_RE = re.compile(r"^\s*\.set\s*=\s*(?P<setter>[A-Za-z_][A-Za-z0-9_]*)\b")
ENTRY_FIELD_RE = re.compile(
    r"^\s*\.(?P<field>cap_id|min|max|value|default_value|def)\s*=\s*(?P<value>[^,]+)"
)
ZERO_LITERAL_RE = re.compile(r"^(?:0[xX]0+|0)(?:[uUlL]+)?$|^(?:false|FALSE|NULL)$")
ZERO_REJECT_GUARD_RE = re.compile(
    r"if\s*\((?P<cond>[^)]*(?:!\s*[A-Za-z_][A-Za-z0-9_]*|"
    r"[A-Za-z_][A-Za-z0-9_]*\s*(?:==|<=|<)\s*0)[^)]*)\)\s*"
    r"(?:\{\s*)?return\s*-\w+\s*;",
    re.DOTALL,
)
CALLBACK_REPLAY_LINE_RE = re.compile(
    r"^\s*(?:if\s*\([^)]*\)\s*)?(?P<expr>[A-Za-z_][A-Za-z0-9_]*(?:->|\.)set)\s*\([^;]+\);\s*$"
)


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


def changed_functions_by_file(patch_text: str) -> dict[str, list[str]]:
    functions: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    current_path = ""
    for line in patch_text.splitlines():
        file_match = DIFF_GIT_RE.match(line)
        if file_match:
            current_path = normalize_path(file_match.group("new"))
            continue
        match = HUNK_RE.match(line)
        if not match or not current_path:
            continue
        context = match.group("context").strip()
        if not context:
            continue
        name_match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", context)
        if not name_match:
            continue
        name = name_match.group(1)
        if name in seen.setdefault(current_path, set()):
            continue
        seen[current_path].add(name)
        functions.setdefault(current_path, []).append(name)
    return functions


def changed_functions(patch_text: str) -> list[str]:
    functions: list[str] = []
    seen: set[str] = set()
    for names in changed_functions_by_file(patch_text).values():
        for name in names:
            if name not in seen:
                seen.add(name)
                functions.append(name)
    return functions


def token_summary(text: str) -> dict[str, int]:
    return {name: len(pattern.findall(text)) for name, pattern in TOKEN_PATTERNS.items()}


def source_file(path: str) -> bool:
    return Path(path).suffix in SOURCE_SUFFIXES


def dt_binding_header(path: str) -> bool:
    return bool(DT_BINDING_HEADER_RE.search(path))


def function_level_source_file(path: str) -> bool:
    return source_file(path) and not dt_binding_header(path)


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


def patch_sections(patch_text: str) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    current_path = ""
    current_lines: list[str] = []
    for line in patch_text.splitlines():
        match = DIFF_GIT_RE.match(line)
        if match:
            if current_path:
                sections.append({"path": current_path, "lines": current_lines})
            current_path = normalize_path(match.group("new"))
            current_lines = []
            continue
        if current_path:
            current_lines.append(line)
    if current_path:
        sections.append({"path": current_path, "lines": current_lines})
    return sections


def added_lines(section: dict[str, object]) -> list[str]:
    lines = section.get("lines", [])
    if not isinstance(lines, list):
        return []
    return [
        line[1:]
        for line in lines
        if isinstance(line, str)
        and line.startswith("+")
        and not line.startswith("+++")
    ]


def removed_lines(section: dict[str, object]) -> list[str]:
    lines = section.get("lines", [])
    if not isinstance(lines, list):
        return []
    return [
        line[1:]
        for line in lines
        if isinstance(line, str)
        and line.startswith("-")
        and not line.startswith("---")
    ]


def source_root_file(source_root: Path | None, relpath: str) -> Path | None:
    if source_root is None:
        return None
    candidate = source_root / relpath
    return candidate if candidate.is_file() else None


def _section_visible_lines(section: dict[str, object]) -> list[str]:
    lines = section.get("lines", [])
    if not isinstance(lines, list):
        return []
    visible: list[str] = []
    for line in lines:
        if not isinstance(line, str) or not line:
            continue
        if line[0] not in {" ", "+"} or line.startswith("+++"):
            continue
        visible.append(line[1:])
    return visible


def _local_declaration(section: dict[str, object], local_name: str) -> str | None:
    for line in _section_visible_lines(section):
        match = LOCAL_DECL_RE.match(line)
        if not match:
            continue
        if match.group("name") != local_name:
            continue
        if line.lstrip().startswith("static "):
            return None
        return line.strip()
    return None


def _extract_function_body(text: str, name: str) -> str | None:
    match = re.search(
        rf"^[A-Za-z_][\w\s\*]*\s+{re.escape(name)}\s*\([^;]*\)\s*\{{",
        text,
        re.MULTILINE,
    )
    if not match:
        return None
    start = match.start()
    brace_pos = text.find("{", match.start())
    if brace_pos < 0:
        return None
    depth = 0
    for index in range(brace_pos, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _visible_window(lines: list[str], index: int, before: int = 12, after: int = 4) -> list[str]:
    start = max(0, index - before)
    end = min(len(lines), index + after + 1)
    return lines[start:end]


def _zero_contract_value(raw: str) -> bool:
    return bool(ZERO_LITERAL_RE.fullmatch(raw.strip()))


def _ignored_callback_replay_paths(
    source_root: Path | None,
    relpaths: Iterable[str],
) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    if source_root is None:
        return hits
    for relpath in relpaths:
        file_path = source_root_file(source_root, relpath)
        if file_path is None:
            continue
        try:
            lines = read_text(file_path).splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines):
            match = CALLBACK_REPLAY_LINE_RE.match(line)
            if not match:
                continue
            prefix = line.split(match.group("expr"), 1)[0]
            if "=" in prefix or "return" in prefix:
                continue
            context = lines[max(0, index - 8):min(len(lines), index + 3)]
            if not any(re.search(r"\bfor\s*\(", prev) for prev in lines[max(0, index - 8):index + 1]):
                continue
            if not any(
                "fw_caps" in candidate
                or "cap->cap_id" in candidate
                or "iris_valid_cap_id" in candidate
                for candidate in context
            ):
                continue
            key = (relpath, line.strip())
            if key in seen:
                continue
            seen.add(key)
            hits.append({
                "path": relpath,
                "line": line.strip(),
            })
    return hits


def _status_var_checked(line: str, status_var: str) -> bool:
    return bool(re.search(
        rf"\bif\s*\(\s*(?:unlikely\s*\(\s*)?{re.escape(status_var)}\b|"
        rf"\breturn\s+{re.escape(status_var)}\b|"
        rf"\bWARN_ON\s*\(\s*{re.escape(status_var)}\b|"
        rf"\b{re.escape(status_var)}\s*\?\s*",
        line,
    ))


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


def find_helper_def_map(
    source_root: Path | None, files: Iterable[str], helpers: Iterable[str]
) -> dict[str, list[str]]:
    if source_root is None:
        return {}
    helper_set = set(helpers)
    if not helper_set:
        return {}
    found: dict[str, list[str]] = {helper: [] for helper in sorted(helper_set)}
    seen: dict[str, set[str]] = {helper: set() for helper in helper_set}
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
                name = match.group("name")
                if name not in helper_set:
                    continue
                relpath = str(path.relative_to(source_root))
                if relpath in seen[name]:
                    continue
                seen[name].add(relpath)
                found[name].append(relpath)
    return {name: paths for name, paths in found.items() if paths}


def find_helper_defs(source_root: Path | None, files: Iterable[str], helpers: Iterable[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for paths in find_helper_def_map(source_root, files, helpers).values():
        for relpath in paths:
            if relpath not in seen:
                seen.add(relpath)
                found.append(relpath)
    return found


def helper_facts(
    sections: list[dict[str, object]],
    source_root: Path | None,
    files: Iterable[str],
    helpers: Iterable[str],
) -> list[dict[str, object]]:
    helper_list = sorted(set(helpers))
    definitions = find_helper_def_map(source_root, files, helper_list)
    facts: list[dict[str, object]] = []
    for helper in helper_list:
        callsite_files: list[str] = []
        seen_callsites: set[str] = set()
        for section in sections:
            path = str(section.get("path", ""))
            if not path or path in seen_callsites:
                continue
            for line in added_lines(section):
                if re.search(rf"\b{re.escape(helper)}\s*\(", line):
                    seen_callsites.add(path)
                    callsite_files.append(path)
                    break
        facts.append({
            "name": helper,
            "callsite_files": callsite_files,
            "definition_files": definitions.get(helper, []),
            "reason": "helper-name-pattern",
        })
    return facts


def dt_facts(
    sections: list[dict[str, object]],
    source_root: Path | None,
    wrapper_schema_files: list[str],
) -> list[dict[str, object]]:
    facts: list[dict[str, object]] = []
    for section in sections:
        path = str(section.get("path", ""))
        if not dt_file(path):
            continue
        added = "\n".join(added_lines(section))
        compatible_strings: list[str] = []
        seen_compat: set[str] = set()
        for match in COMPATIBLE_STRING_RE.finditer(added):
            value = match.group("dts") or match.group("const")
            if value and value not in seen_compat:
                seen_compat.add(value)
                compatible_strings.append(value)
        facts.append({
            "path": path,
            "compatible_strings": compatible_strings,
            "defines_dmas": bool(re.search(r"^\s*dmas\s*:", added, re.MULTILINE)),
            "defines_dma_names": bool(re.search(r"^\s*dma-?names\s*:", added, re.MULTILINE)),
            "example_has_dmas": bool(re.search(r"dmas\s*=\s*<", added, re.IGNORECASE)),
            "example_has_dma_names": bool(re.search(r"dma-?names\s*=\s*[\"<]", added, re.IGNORECASE)),
            "referenced_schemas": [p for p in wrapper_schema_files if Path(p).suffix in {".yaml", ".yml"}],
        })
    return facts


def runtime_pm_facts(
    sections: list[dict[str, object]],
    source_root: Path | None,
    source_files: Iterable[str],
) -> dict[str, object]:
    added_calls: list[dict[str, str]] = []
    for section in sections:
        path = str(section.get("path", ""))
        for line in added_lines(section):
            for match in PM_RUNTIME_API_RE.finditer(line):
                added_calls.append({"path": path, "api": match.group(0).split("(", 1)[0]})
    bare_get_sync_files: list[str] = []
    seen_bare: set[str] = set()
    for relpath in source_files:
        texts: list[str] = []
        file_path = source_root_file(source_root, relpath)
        if file_path is not None:
            try:
                texts.append(read_text(file_path))
            except OSError:
                pass
        for section in sections:
            if section.get("path") == relpath:
                texts.append("\n".join(added_lines(section)))
        if any(BARE_PM_RUNTIME_GET_SYNC_RE.search(text) for text in texts):
            if relpath not in seen_bare:
                seen_bare.add(relpath)
                bare_get_sync_files.append(relpath)
    return {
        "added_calls": added_calls,
        "added_get_sync_calls": [call for call in added_calls if call.get("api") == "pm_runtime_get_sync"],
        "bare_get_sync_files": bare_get_sync_files,
    }


def match_data_facts(sections: list[dict[str, object]]) -> dict[str, object]:
    assignments: list[dict[str, object]] = []
    unguarded: list[dict[str, object]] = []
    for section in sections:
        path = str(section.get("path", ""))
        added = added_lines(section)
        added_text = "\n".join(added)
        for match in MATCH_DATA_ASSIGN_RE.finditer(added_text):
            expr = match.group("expr")
            dereferenced = bool(re.search(rf"\b{re.escape(expr)}\s*->", added_text))
            guarded = bool(re.search(
                rf"(?:if\s*\(\s*!\s*{re.escape(expr)}\s*\)|"
                rf"IS_ERR_OR_NULL\s*\(\s*{re.escape(expr)}\s*\)|"
                rf"!{re.escape(expr)}\s*\?)",
                added_text,
            ))
            fact = {
                "path": path,
                "expr": expr,
                "api": match.group("api"),
                "dereferenced": dereferenced,
                "guarded": guarded,
            }
            assignments.append(fact)
            if dereferenced and not guarded:
                unguarded.append(fact)
    return {"assignments": assignments, "unguarded_dereferences": unguarded}


def lifetime_facts(sections: list[dict[str, object]]) -> dict[str, object]:
    escaped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for section in sections:
        path = str(section.get("path", ""))
        for line in added_lines(section):
            for match in ESCAPED_LOCAL_FIELD_STORE_RE.finditer(line):
                local = match.group("local")
                declaration = _local_declaration(section, local)
                if declaration is None:
                    continue
                key = (path, match.group("target"), local)
                if key in seen:
                    continue
                seen.add(key)
                escaped.append({
                    "path": path,
                    "local": local,
                    "target": match.group("target"),
                    "store_kind": "field_store",
                    "line": line.strip(),
                    "declaration": declaration,
                })
            for match in ESCAPED_LOCAL_API_STORE_RE.finditer(line):
                local = match.group("local")
                declaration = _local_declaration(section, local)
                if declaration is None:
                    continue
                key = (path, match.group("api"), local)
                if key in seen:
                    continue
                seen.add(key)
                escaped.append({
                    "path": path,
                    "local": local,
                    "target": match.group("api"),
                    "store_kind": "retained_state_api",
                    "line": line.strip(),
                    "declaration": declaration,
                })
            for match in ESCAPED_LOCAL_GENERIC_CALL_RE.finditer(line):
                local = match.group("local")
                declaration = _local_declaration(section, local)
                if declaration is None:
                    continue
                if not _SCALAR_DECL_RE.match(declaration):
                    continue
                key = (path, match.group("api"), local)
                if key in seen:
                    continue
                seen.add(key)
                escaped.append({
                    "path": path,
                    "local": local,
                    "target": match.group("api"),
                    "store_kind": "generic_call_arg",
                    "line": line.strip(),
                    "declaration": declaration,
                })
    return {"escaped_local_address_stores": escaped}


def setup_flow_facts(sections: list[dict[str, object]]) -> dict[str, object]:
    unchecked: list[dict[str, str]] = []
    for section in sections:
        path = str(section.get("path", ""))
        lines = added_lines(section)
        for index, line in enumerate(lines):
            match = SETUP_RESULT_ASSIGN_RE.match(line)
            if not match:
                continue
            helper = match.group("helper")
            if not SETUP_HELPER_NAME_RE.search(helper):
                continue
            status = match.group("status")
            publish_call = ""
            checked = False
            for next_line in lines[index + 1:index + 7]:
                if re.search(rf"^\s*{re.escape(status)}\s*=", next_line):
                    break
                if _status_var_checked(next_line, status):
                    checked = True
                    break
                publish = PUBLISH_CALL_RE.search(next_line)
                if publish:
                    publish_call = publish.group("call")
                    break
            if publish_call and not checked:
                unchecked.append({
                    "path": path,
                    "status_var": status,
                    "helper": helper,
                    "publish_call": publish_call,
                    "line": line.strip(),
                })
    return {"unchecked_setup_before_publish": unchecked}


def admission_control_facts(sections: list[dict[str, object]]) -> dict[str, object]:
    missing_peer_checks: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for section in sections:
        path = str(section.get("path", ""))
        visible_text = "\n".join(_section_visible_lines(section))
        added = added_lines(section)
        for left, right in DIMENSION_PAIRS:
            if not re.search(rf"\b{re.escape(left)}\b", visible_text, re.IGNORECASE):
                continue
            if not re.search(rf"\b{re.escape(right)}\b", visible_text, re.IGNORECASE):
                continue
            guarded: dict[str, str] = {}
            for line in added:
                if not CAPACITY_GUARD_RE.search(line):
                    continue
                for dimension in (left, right):
                    if re.search(rf"\b{re.escape(dimension)}\b", line, re.IGNORECASE):
                        guarded.setdefault(dimension, line.strip())
            if left in guarded and right not in guarded:
                key = (path, left, right, guarded[left])
                if key not in seen:
                    seen.add(key)
                    missing_peer_checks.append({
                        "path": path,
                        "checked_dimension": left,
                        "missing_dimension": right,
                        "line": guarded[left],
                    })
            if right in guarded and left not in guarded:
                key = (path, right, left, guarded[right])
                if key not in seen:
                    seen.add(key)
                    missing_peer_checks.append({
                        "path": path,
                        "checked_dimension": right,
                        "missing_dimension": left,
                        "line": guarded[right],
                    })
    return {"missing_peer_dimension_checks": missing_peer_checks}


def _status_error_exit(line: str, status_var: str) -> bool:
    return bool(re.search(
        rf"\bif\s*\([^)]*\b{re.escape(status_var)}\b[^)]*\)|"
        rf"\breturn\s+{re.escape(status_var)}\b|"
        rf"\bgoto\s+err\w*\b",
        line,
        re.IGNORECASE,
    ))


def stale_state_facts(sections: list[dict[str, object]]) -> dict[str, object]:
    stale: list[dict[str, str]] = []
    for section in sections:
        path = str(section.get("path", ""))
        lines = added_lines(section)
        for index, line in enumerate(lines):
            state_match = STATE_FIELD_ASSIGN_RE.match(line)
            if not state_match:
                continue
            state_target = state_match.group("target")
            state_value = state_match.group("value").strip()
            if not STATE_SUCCESS_VALUE_RE.search(state_value):
                continue
            operation = ""
            status_var = ""
            operation_index = -1
            for next_index, next_line in enumerate(lines[index + 1:index + 7], start=index + 1):
                start_match = START_RESULT_ASSIGN_RE.match(next_line)
                if not start_match:
                    continue
                operation = start_match.group("operation")
                status_var = start_match.group("status")
                operation_index = next_index
                break
            if operation_index < 0:
                continue
            error_exit = ""
            cleared = False
            for next_line in lines[operation_index + 1:operation_index + 8]:
                if state_target in next_line and re.search(r"=\s*(?:false|0|NULL|OFF|IDLE|STOPPED)\b", next_line):
                    cleared = True
                    break
                if _status_error_exit(next_line, status_var):
                    error_exit = next_line.strip()
                    break
            if error_exit and not cleared:
                stale.append({
                    "path": path,
                    "state_target": state_target,
                    "state_value": state_value,
                    "operation": operation,
                    "status_var": status_var,
                    "error_exit": error_exit,
                    "line": line.strip(),
                })
    return {"failed_start_stale_state": stale}


def resource_facts(sections: list[dict[str, object]]) -> dict[str, object]:
    helper_calls: list[dict[str, str]] = []
    abstraction_calls: list[dict[str, str]] = []
    removed_gets: list[dict[str, str]] = []
    duplicate_teardown_calls: list[dict[str, object]] = []
    for section in sections:
        path = str(section.get("path", ""))
        teardown_lines: dict[str, list[str]] = {}
        for line in added_lines(section):
            if TOKEN_PATTERNS["resource_helper"].search(line):
                helper_calls.append({"path": path, "line": line.strip()})
            if RESOURCE_ABSTRACTION_RE.search(line):
                abstraction_calls.append({"path": path, "line": line.strip()})
            for match in TEARDOWN_CALL_RE.finditer(line):
                teardown_lines.setdefault(match.group("call"), []).append(line.strip())
        for line in removed_lines(section):
            match = RESOURCE_GET_REMOVED_RE.search(line)
            if not match:
                continue
            resource = match.group("resource")
            if resource in RESOURCE_GET_GUARD_EXCLUSIONS:
                continue
            removed_gets.append({"path": path, "resource": resource, "line": line.strip()})
        for call, hits in sorted(teardown_lines.items()):
            if len(hits) < 2:
                continue
            duplicate_teardown_calls.append({
                "path": path,
                "call": call,
                "count": len(hits),
                "lines": hits[:4],
            })
    return {
        "helper_calls": helper_calls,
        "abstraction_candidates": abstraction_calls,
        "removed_gets": removed_gets,
        "duplicate_teardown_calls": duplicate_teardown_calls,
    }


def setter_contract_facts(
    sections: list[dict[str, object]],
    source_root: Path | None,
    files: Iterable[str],
) -> dict[str, object]:
    rewired: list[dict[str, str]] = []
    seen_rewired: set[tuple[str, str, str, str]] = set()
    for section in sections:
        path = str(section.get("path", ""))
        visible = _section_visible_lines(section)
        for index, line in enumerate(visible):
            match = SETTER_ASSIGN_RE.match(line)
            if not match:
                continue
            setter = match.group("setter")
            window = _visible_window(visible, index)
            fields: dict[str, str] = {}
            for candidate in window:
                field_match = ENTRY_FIELD_RE.match(candidate)
                if not field_match:
                    continue
                fields[field_match.group("field")] = field_match.group("value").strip()
            min_value = fields.get("min", "")
            default_value = fields.get("value", "") or fields.get("default_value", "") or fields.get("def", "")
            if not (_zero_contract_value(min_value) or _zero_contract_value(default_value)):
                continue
            cap_id = fields.get("cap_id", "")
            key = (path, cap_id, setter, min_value or default_value)
            if key in seen_rewired:
                continue
            seen_rewired.add(key)
            rewired.append({
                "path": path,
                "cap_id": cap_id,
                "setter": setter,
                "min_value": min_value,
                "default_value": default_value,
            })

    if not rewired:
        return {"newly_exposed_silent_failures": []}

    setter_defs = find_helper_def_map(source_root, files, [item["setter"] for item in rewired])
    reject_guards: dict[str, dict[str, str]] = {}
    search_files = {
        relpath
        for paths in setter_defs.values()
        for relpath in paths
    }
    for relpath in search_files:
        file_path = source_root_file(source_root, relpath)
        if file_path is None:
            continue
        try:
            text = read_text(file_path)
        except OSError:
            continue
        for setter, paths in setter_defs.items():
            if relpath not in paths:
                continue
            body = _extract_function_body(text, setter)
            if not body:
                continue
            guard_match = ZERO_REJECT_GUARD_RE.search(body)
            if not guard_match:
                continue
            reject_guards[setter] = {
                "definition_path": relpath,
                "guard": " ".join(guard_match.group("cond").split()),
            }

    replay_paths = _ignored_callback_replay_paths(source_root, files)
    if not replay_paths:
        return {"newly_exposed_silent_failures": []}

    facts: list[dict[str, object]] = []
    for item in rewired:
        reject = reject_guards.get(item["setter"])
        if not reject:
            continue
        facts.append({
            "path": item["path"],
            "cap_id": item["cap_id"],
            "setter": item["setter"],
            "min_value": item["min_value"],
            "default_value": item["default_value"],
            "reject_guard": reject["guard"],
            "setter_definition_path": reject["definition_path"],
            "replay_paths": replay_paths,
        })
    return {"newly_exposed_silent_failures": facts}


def build_manifest(
    patch_file: Path,
    patch_number: int,
    output: Path,
    source_root: Path | None,
) -> dict[str, object]:
    patch_text = read_text(patch_file)
    files = parse_patch_files(patch_text)
    sections = patch_sections(patch_text)
    changed = changed_lines(patch_text)
    source_files = [path for path in files if source_file(path)]
    function_source_files = [path for path in source_files if function_level_source_file(path)]
    dt_files = [path for path in files if dt_file(path)]
    dt_binding_headers = [path for path in files if dt_binding_header(path)]
    build_files = [path for path in files if build_file(path)]
    functions_by_file = changed_functions_by_file(patch_text)
    functions = changed_functions(patch_text)
    helpers = helper_candidates(patch_text)
    helper_def_files = find_helper_defs(source_root, files, helpers)
    wrapper_schema_files = yaml_refs(source_root, dt_files)

    reads: list[dict[str, str | bool]] = []
    seen_reads: set[str] = set()
    for relpath, reason in [
        *[(path, "touched_source") for path in function_source_files],
        *[(path, "dt_binding_header") for path in dt_binding_headers],
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
        "function_level_source_files": function_source_files,
        "changed_dt_files": dt_files,
        "changed_dt_binding_headers": dt_binding_headers,
        "changed_build_files": build_files,
        "changed_functions": functions,
        "changed_functions_by_file": functions_by_file,
        "helper_candidates": helpers,
        "helper_facts": helper_facts(sections, source_root, files, helpers),
        "dt_facts": dt_facts(sections, source_root, wrapper_schema_files),
        "runtime_pm_facts": runtime_pm_facts(sections, source_root, source_files),
        "match_data_facts": match_data_facts(sections),
        "lifetime_facts": lifetime_facts(sections),
        "setup_flow_facts": setup_flow_facts(sections),
        "admission_control_facts": admission_control_facts(sections),
        "stale_state_facts": stale_state_facts(sections),
        "resource_facts": resource_facts(sections),
        "setter_contract_facts": setter_contract_facts(sections, source_root, source_files),
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
