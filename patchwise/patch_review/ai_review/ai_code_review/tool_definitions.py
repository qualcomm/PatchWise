# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Tool definitions in LiteLLM/OpenAI format for the AiCodeReview agent.

All tools accept and return kernel-relative paths (e.g. 'drivers/usb/foo.c').
The `file` arg on name-taking tools is a hint for where you saw the symbol
used, not where its definition lives. The tool resolves the definition
itself. List tools cap results at 100; read_file caps at 200 lines.
"""

_NAME_PARAM = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "The symbol name.",
        },
        "file": {
            "type": "string",
            "description": (
                "Optional kernel-relative path where you saw the symbol "
                "used. This is a disambiguation hint only, NOT the file "
                "where the definition lives. Example: if a patch in "
                "drivers/usb/foo.c calls bar(), pass file='drivers/usb/foo.c'."
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
                "Find the declaration and definition of a symbol by name. "
                "Returns {declaration, definition, alternatives?}: declaration "
                "is the header-side prototype (may be null if same as definition); "
                "definition is the implementation with full body. Alternatives are "
                "included (capped at 5) only when the best pick is outside files "
                "you have already seen and there is ambiguity."
            ),
            "parameters": _NAME_PARAM,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_callers",
            "description": (
                "One level of incoming call hierarchy for a function: who "
                "calls this function. Returns an error for non-function "
                "symbols (use grep for structs, macros, variables, etc.). "
                "Each result is {name, path, line, snippet}. Capped at 100; "
                "'total' and 'truncated' indicate overflow."
            ),
            "parameters": _NAME_PARAM,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_calls",
            "description": (
                "One level of outgoing call hierarchy for a function: what this "
                "function calls. Each result is {name, path, line, snippet}. "
                "Fails with an error if the symbol is not a function. "
                "Capped at 100; 'total' and 'truncated' indicate overflow."
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
                "Each result is {path, line, snippet, enclosing_function}: "
                "enclosing_function names the function the hit sits inside, or "
                "is null for hits at file scope (macro definitions, struct/enum "
                "declarations, static initializers, EXPORT_SYMBOL_*, etc.). "
                "Capped at 100; 'total' and 'truncated' indicate overflow. "
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
                        "type": "string",
                        "description": "Optional kernel-relative file to restrict the search to.",
                    },
                    "glob": {
                        "type": "string",
                        "description": (
                            "Comma-separated ripgrep glob patterns to filter which files "
                            "are searched (e.g. '*.dts,*.dtsi,*.yaml' or 'Kconfig,Makefile'). "
                            "Ignored when `file` is set. Defaults to '*.c,*.h'."
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
                "200 lines per call. If `truncated` is true, call again with "
                "a later `start` to read more."
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
                        "description": "1-based ending line, inclusive (default start+199).",
                    },
                },
                "required": ["path"],
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
]
