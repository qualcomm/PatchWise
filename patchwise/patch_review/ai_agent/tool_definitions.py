# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Tool definitions in LiteLLM/OpenAI format for the agent.

All tools accept and return kernel-relative paths (e.g. 'drivers/usb/foo.c').
The `file` arg on name-taking tools is a hint for where you saw the symbol
used, not where its definition lives. The tool resolves the definition
itself. List tools cap results at 100; read_file and git_cat_file cap at
256 lines; git_show caps at 200.
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
                "Optional kernel-relative path(s) where you saw the symbol used, "
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
                            "Optional kernel-relative file(s)/dir(s) to scope the search, "
                            "one path per array element. Glob is ignored for single files."
                        ),
                    },
                    "glob": {
                        "type": "string",
                        "description": (
                            "Comma-separated ripgrep glob patterns. Defaults to '*.c,*.h'."
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
                "Read lines [start, end] of a kernel-relative file. Capped at "
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
                        "description": "Kernel-relative path, e.g. 'drivers/gpio/gpio-foo.c'.",
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
                        "description": "Kernel-relative path under Documentation/.",
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
            "name": "list_files",
            "description": (
                "List files and directories at a kernel-relative path. Set "
                "recursive=true for a deep listing. Hidden entries (dotfiles/dirs "
                "such as .git) are filtered out. Result is "
                "{entries: [{name, type: 'file'|'dir'}], total, truncated}. "
                "Capped at 100 entries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Kernel-relative directory path (use '.' for the kernel root).",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Whether to walk subdirectories (default false).",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": (
                "Search commit history. Returns {result: [{rev, author, date, "
                "subject}], total, truncated}, capped at 100 commits. Give at "
                "least one criterion: `path` (history of a file/dir), `grep` "
                "(commit-message regex), `pickaxe` (commits that added or "
                "removed an exact string — when a symbol/line was introduced or "
                "deleted), or `pickaxe_regex` (commits whose diff adds/removes a "
                "line matching a regex). Combine them to narrow, e.g. pickaxe + "
                "path to find where a symbol entered one file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Kernel-relative file or directory path to scope the "
                            "search to (optional when a search criterion is given)."
                        ),
                    },
                    "grep": {
                        "type": "string",
                        "description": "Regex matched against commit messages (--grep).",
                    },
                    "pickaxe": {
                        "type": "string",
                        "description": (
                            "Exact string; finds commits that changed how many "
                            "times it occurs, i.e. added or removed it (-S)."
                        ),
                    },
                    "pickaxe_regex": {
                        "type": "string",
                        "description": (
                            "Regex; finds commits whose diff adds or removes any "
                            "line matching it (-G)."
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
            "name": "git_show",
            "description": (
                "Show a commit or historical file object by revision. `rev` may "
                "be a commit id/revision (e.g. HEAD~1) or `<commit-id>:<relative/path>` "
                "(e.g. `43cfbdda5af6:drivers/remoteproc/qcom_q6v5.c`). Set "
                "`name_only=true` to return only changed file paths for a commit. "
                "Returns {rev, content, truncated} or {rev, paths, truncated}. "
                "Capped at 200 lines or 200 paths per call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rev": {
                        "type": "string",
                        "description": (
                            "A commit revision such as HEAD, HEAD~1, or a commit SHA, "
                            "or a historical file object like "
                            "'43cfbdda5af6:drivers/remoteproc/qcom_q6v5.c'."
                        ),
                    },
                    "name_only": {
                        "type": "boolean",
                        "description": (
                            "If true, return only the changed file paths for the commit."
                        ),
                    },
                },
                "required": ["rev"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_cat_file",
            "description": (
                "Read a historical file from git by commit revision and kernel-relative "
                "path. Returns {rev, path, start, end, total, content}: "
                "lines start..end of `total` (end < total means more remains). "
                "Capped at 256 lines per call. Use this when `git_show` output is "
                "truncated or when you want file contents without a patch."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rev": {
                        "type": "string",
                        "description": "A commit revision such as HEAD, HEAD~1, or a commit SHA.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Kernel-relative path inside that revision.",
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
                "required": ["rev", "path"],
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
                            "Where the issue is: kernel-relative file and line or "
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
                        "description": "Kernel-relative path, e.g. 'drivers/i2c/foo.c'.",
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

# Read-only code-navigation tools; loops that scope themselves with
# allowed_tools start from this set and append the few extras they need.
NAVIGATION_TOOLS = [
    "find_definition",
    "find_callers",
    "find_callees",
    "grep",
    "read_file",
    "read_doc",
    "read_binding",
    "search_docs",
    "list_files",
    "git_log",
    "git_show",
    "git_cat_file",
]
