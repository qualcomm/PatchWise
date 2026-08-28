# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Tool definitions in LiteLLM/OpenAI format for the agent.

All tools accept and return workspace-relative paths (e.g. 'drivers/usb/foo.c').
The `file` arg on name-taking tools is a hint for where you saw the symbol
used, not where its definition lives. The tool resolves the definition
itself. List tools cap results at 100; read_file caps at 256 lines.

The navigation tools return *structured* results — line spans, the enclosing
construct, every arch/#ifdef variant ranked — which is what they exist for.
`bash` covers everything else the container can do (history, lint, build,
one-off composition) without a bespoke schema per command; it returns plain
text, so reach for the navigation tools when you want positions rather than
prose.
"""

_NAME_PARAM = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "The symbol name.",
        },
        "file": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Optional workspace-relative path(s) where you saw the symbol used, "
                "one path per array element. A ranking hint; the definition may "
                "live elsewhere."
            ),
        },
    },
    "required": ["name"],
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_definition",
            "description": (
                "Find every definition of a symbol (function, struct, union, "
                "enum, typedef, macro, or ops-table/aggregate initializer such "
                "as `static const struct x_ops foo_ops = {...}`). Each arch/"
                "#ifdef variant is a separate result, best-first by proximity. "
                "Result: {name, kind, path, line, end, snippet} — kind names "
                "which it is; the definition spans lines [line, end], so "
                "read_file(path, line, end) returns it whole; `truncated` flags "
                "overflow."
            ),
            "parameters": _NAME_PARAM,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_callers",
            "description": (
                "Find what references a symbol. Returns {callers, references}: "
                "`callers` is one entry per function {function, path, "
                "function_start, function_end, lines, snippet} — read_file(path, "
                "function_start, function_end) returns the whole calling "
                "function; `references` is file-scope hits {path, line, snippet} "
                "(e.g. `.release = name` wiring, annotated with the enclosing "
                "construct); `truncated` flags overflow. Textual match — verify "
                "the subsystem for common names."
            ),
            "parameters": _NAME_PARAM,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_callees",
            "description": (
                "Find what a function calls. Returns one entry per definition "
                "{path, line, callees}; each callee is {name, line, kind} — kind "
                "'direct' (foo()) or 'indirect' (ops->fn()). Pass `file` to pick "
                "a variant."
            ),
            "parameters": _NAME_PARAM,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": (
                "Search for a regex pattern across the kernel source tree. "
                "Each result is {path, line, snippet, enclosing}. `enclosing` is "
                "the innermost construct containing the hit — {name, kind, start, "
                "end} where kind is one of function, struct, union, enum, typedef, "
                "macro, initializer (an ops-table / aggregate initializer) — so a "
                "hit is oriented whether it is in a function body or at file scope "
                "(a struct member, a macro body, a `.release = foo` ops-table "
                "entry). read_file(path, start, end) returns the whole construct. "
                "It is null only outside every indexed construct. "
                "Capped at 100; 'total' and 'truncated' indicate overflow. "
                "Set `count_only` to return only the number of matching lines, "
                "without snippets or enclosing constructs. "
                "If some scoped paths don't exist, the search still runs over "
                "the rest and lists the dropped ones in 'skipped_paths'. "
                "By default searches *.c and *.h only. Use `glob` to widen: "
                "e.g. '*.dts,*.dtsi,*.yaml' for DT/binding reviews, "
                "'Kconfig,Makefile' for build-system searches."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Ripgrep regex (Rust-style).",
                    },
                    "file": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional workspace-relative file(s)/dir(s) to scope the search, "
                            "one path per array element. Glob is ignored for single files."
                        ),
                    },
                    "glob": {
                        "type": "string",
                        "description": (
                            "Comma-separated ripgrep glob patterns. Defaults to '*.c,*.h'."
                        ),
                    },
                    "count_only": {
                        "type": "boolean",
                        "description": (
                            "Return only {ok, count} instead of individual hits. "
                            "Use for existence/count checks."
                        ),
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read lines [start, end] of a workspace-relative file. Capped at "
                "256 lines per call. Returns {path, start, end, total, content}: "
                "you have lines start..end of `total`, so end < total means more "
                "remains (call again with start = end + 1) and end == total is "
                "end-of-file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative path, e.g. 'drivers/gpio/gpio-foo.c'.",
                    },
                    "start": {
                        "type": "integer",
                        "description": "1-based starting line (default 1).",
                    },
                    "end": {
                        "type": "integer",
                        "description": "1-based ending line, inclusive (default start+255).",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_doc",
            "description": (
                "Read a whole kernel Documentation/ file (e.g. "
                "'Documentation/filesystems/mmap_prepare.rst') to check a "
                "documented contract, ABI, or interface promise. Restricted to "
                "Documentation/; returns the full file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path under Documentation/.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_binding",
            "description": (
                "Resolve a devicetree `compatible` pattern to its binding "
                "documentation and return the yaml(s) whole. Greps "
                "Documentation/devicetree/bindings/ for the compatible. "
                "Result: {matches: [{path, content}]}, deduped by path. Use "
                "this instead of guessing the Documentation/devicetree/bindings/ "
                "path."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "compatible": {
                        "type": "string",
                        "description": (
                            "A ripgrep regex for the devicetree compatible: a "
                            "literal like 'qcom,sm8550-adsp-pas' matches itself; "
                            "a pattern like 'qcom,sm8[0-9]50-.*-adsp-pas' or an "
                            "alternation 'qcom,foo|qcom,bar' matches several."
                        ),
                    },
                },
                "required": ["compatible"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": (
                "Search the kernel Documentation/ tree for a topic, symbol, or "
                "compatible to find the right doc. Returns matching {path, line, "
                "snippet}; read the chosen file whole with read_doc(path). Use "
                "this to locate a documented contract, ABI, or interface by "
                "content instead of guessing its path. For a devicetree "
                "compatible, read_binding is more direct."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Ripgrep regex to search Documentation/ contents "
                            "for, e.g. a symbol, topic word, or compatible."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_subsystem_review_guide",
            "description": (
                "Load a subsystem-specific review guide by filename. Use the "
                "Subsystem Review Guide Index in the system prompt to pick "
                "guides whose triggers match the paths and symbols touched by "
                "this patch. Returns {name, content}; the content is the full "
                "guide to apply when reviewing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subsystem_file": {
                        "type": "string",
                        "description": (
                            "The bare .md filename from the Subsystem Review "
                            "Guide Index (e.g. 'networking-core.md', 'rcu.md'). "
                        ),
                    },
                },
                "required": ["subsystem_file"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Run a shell command in the container. One-shot: each call is a "
                "fresh exec, so no state (cwd, variables, environment) carries "
                "over — chain related steps with `&&` or `;` in one command. "
                "stdout and stderr are merged; output is truncated past a size "
                "cap, and the command is killed after 120s. "
                "Example usage: git history, one-off shell composition, "
                "build/config inspection, etc. For searching and reading source, "
                "prefer the navigation tools — they return line spans and the "
                "enclosing construct, which the bash output does not carry."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command, run via `sh -c`.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": (
                            "Working directory, workspace-relative (e.g. "
                            "'drivers/usb') or absolute. Defaults to the "
                            "workspace root."
                        ),
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_finding",
            "description": (
                "Record one confirmed review finding immediately, the moment you "
                "have grounded it in the code. Call this once per finding as you "
                "work through the review — do NOT wait until the end and do "
                "NOT batch them. Each call is appended to your findings file, so "
                "your final message does not need to repeat the findings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": (
                            "Where the issue is: workspace-relative file and line or "
                            "symbol, e.g. 'drivers/x/y.c:123' or 'foo_get()'."
                        ),
                    },
                    "finding": {
                        "type": "string",
                        "description": (
                            "The issue, written as an inline review comment: quote "
                            "the relevant code and explain the bug and its impact."
                        ),
                    },
                    "dimension": {
                        "type": "string",
                        "description": "The analysis dimension this finding came from.",
                    },
                },
                "required": ["location", "finding"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_verdict",
            "description": (
                "Record your verdict on one finding the moment you have judged "
                "it. Call this once per finding as you work through them in order, "
                "so each verdict is saved as you go. Each call is appended to your "
                "verdicts file, so your final message does not need to repeat them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "finding": {
                        "type": "string",
                        "description": (
                            "The finding you judged, copied faithfully (its "
                            "location and review comment), so a kept one survives "
                            "unchanged."
                        ),
                    },
                    "impact": {
                        "type": "string",
                        "description": (
                            "Severity of the defect if real: 'high' (memory "
                            "corruption, crash, security, data loss, deadlock, "
                            "uninitialised/freed memory), 'medium' (a functional "
                            "bug under specific conditions), or 'low' (style, "
                            "robustness, comment/commit-message)."
                        ),
                    },
                    "verdict": {
                        "type": "string",
                        "description": "'keep' or 'drop' (drop = proven false positive).",
                    },
                    "reason": {
                        "type": "string",
                        "description": "One line: why the finding stands or is a false positive.",
                    },
                    "proof": {
                        "type": "string",
                        "description": (
                            "For a drop: the guide rule plus the actual code/contract "
                            "lines that refute it. Leave empty for a keep."
                        ),
                    },
                },
                "required": ["finding", "impact", "verdict"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_add",
            "description": (
                "Add one task to your own checklist. Use this to track anything "
                "you plan to investigate or do — items known up front, follow-ups "
                "you discover along the way, or sub-questions spun off from "
                "another task. Keep the id short and stable; use it later with "
                "task_complete. You may add tasks at any point, not only at the "
                "start."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": (
                            "Short stable identifier for this task, reused by "
                            "task_complete."
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": (
                            "One line: what will be investigated or done."
                        ),
                    },
                },
                "required": ["id", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": (
                "Mark one previously-added task as complete. Call this the moment "
                "you finish a task — after acting on its conclusion, or after "
                "concluding there is nothing more to do for it. Every task_add "
                "MUST eventually be matched by a task_complete."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "The id passed to task_add.",
                    },
                    "result": {
                        "type": "string",
                        "description": (
                            "One word summarising the outcome, e.g. 'done', "
                            "'clean', 'found', 'abandoned'."
                        ),
                    },
                    "note": {
                        "type": "string",
                        "description": (
                            "Optional one-line summary of what was checked and "
                            "why the result is what it is."
                        ),
                    },
                },
                "required": ["id", "result"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_list",
            "description": (
                "Show your current checklist: every task_add so far, and for "
                "each one whether it has been marked complete. Use this to "
                "check what is still open before you stop, or whenever you "
                "lose track of what remains."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_checkpatch",
            "description": (
                "Run scripts/checkpatch.pl on the current uncommitted changes to verify "
                "that checkpatch issues have been fixed. Returns human-readable output "
                "summarizing remaining issues or a success message when none remain."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": (
                            "Optional kernel-relative path to a specific file to focus on. "
                            "If omitted, all modified files in the current diff are checked."
                        ),
                    },
                },
                "required": [],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "run_sparse",
            "description": (
                "Run sparse on modified C source/header files to verify that sparse "
                "warnings and errors have been fixed. Returns human-readable output "
                "summarizing remaining issues or a success message when none remain."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional list of kernel-relative paths to specific files to check. "
                            "If omitted, all modified C and header files in the diff are checked."
                        ),
                    },
                },
                "required": [],
            },
        },
    },

    # write tools
    {
        "type": "function",
        "function": {
            "name": "write_file_str",
            "description": (
                "Replace an exact snippet of text in a file. "
                "Finds old_content verbatim and replaces it with "
                "new_content. Fails if old_content is not found or "
                "matches more than once."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Workspace-relative path, e.g. 'drivers/i2c/foo.c'.",
                    },
                    "old_content": {
                        "type": "string",
                        "description": "Exact text to find and replace.",
                    },
                    "new_content": {
                        "type": "string",
                        "description": "Replacement text.",
                    },
                },
                "required": ["file", "old_content", "new_content"],
            },
        },
    },
]

# The general-purpose working set: structured navigation tools plus `bash`.
# Loops that scope themselves with allowed_tools start from this set and append
# the few extras they need. `bash` is read-only only by convention — it can
# write, so loops that must not modify the tree omit it explicitly.
NAVIGATION_TOOLS = [
    "find_definition",
    "find_callers",
    "find_callees",
    "grep",
    "read_file",
    "read_doc",
    "read_binding",
    "search_docs",
    "bash",
]
