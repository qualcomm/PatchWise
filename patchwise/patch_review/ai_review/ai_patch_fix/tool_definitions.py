# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Tool definitions in LiteLLM/OpenAI format for the AiPatchFix agent.

All tools accept kernel-relative paths (e.g. 'drivers/usb/foo.c') and
operate on files inside the Docker container's kernel tree.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_file_str",
            "description": (
                "Replace an exact snippet of text in a file. "
                "Finds old_content verbatim and replaces it with "
                "new_content. Fails if old_content is not found or "
                "matches more than once. Prefer this over write_file."
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
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Replace a range of lines in a file inside the kernel "
                "source tree. Lines are 1-based and inclusive. Use as a "
                "fallback when write_file_str cannot be used."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Kernel-relative path, e.g. 'drivers/i2c/foo.c'.",
                    },
                    "start": {
                        "type": "integer",
                        "description": "First line to replace (1-based, inclusive).",
                    },
                    "end": {
                        "type": "integer",
                        "description": "Last line to replace (1-based, inclusive).",
                    },
                    "content": {
                        "type": "string",
                        "description": "Replacement text for the line range.",
                    },
                },
                "required": ["file", "start", "end", "content"],
            },
        },
    },
]
