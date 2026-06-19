# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Sparse error fixer using AI with targeted file edits.

This fixer applies script-based fixes first, then uses AI with verification tools.
Includes RAG-based retrieval of kernel documentation for enhanced context.
"""

import os
import re
import tempfile
from pathlib import Path
from typing import List

from patchwise.patch_review.ai_fix import AiFix
from patchwise.patch_review.static_analysis.sparse import Sparse
from patchwise.patch_review.decorators import register_fix

try:
    from patchwise.patch_review.ai_fix.kernel_docs_rag import KernelDocRAG
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False
    KernelDocRAG = None


@register_fix(Sparse)
class SparseFixer(AiFix):
    """AI-powered sparse fixer based on sparse findings.

    This fixer uses a two-stage approach:
    1. Apply script-based fixes for common issues (simple type fixes, etc.)
    2. Use AI with write_file_str/write_file tools AND verification tools
    
    The AI can run sparse to verify fixes, enabling self-correction.
    
    The AI edits files directly inside the Docker container. Those working-tree 
    edits are then folded into HEAD via ``git commit --amend`` and emitted as 
    an mbox patch via ``git format-patch``.

    Returns patch fix output.
    """

    SPARSE_FIX_PROMPT_TEMPLATE = """
# User Prompt

The following patch diff has sparse warnings and errors that need to be fixed.
Script-based fixes have already been applied for simple issues.
Use the write tools to apply fixes for the remaining sparse issues
directly to the source files in the kernel tree.

**IMPORTANT**: After making changes, use the `run_sparse` tool to verify 
that the issues are fixed. If issues remain, iterate and fix them.

## Commit text

{commit_text}

## Current patch diff (after script fixes)

```diff
{diff}
```

## Remaining sparse issues to fix

{sparse_issues}

## Available Tools

1. **write_file_str** / **write_file**: Edit source files
2. **run_sparse**: Verify your fixes by running sparse
3. **read_file**: Read file contents to understand context

## Workflow

1. Make targeted edits to fix issues
2. Run `run_sparse` to verify fixes
3. If issues remain, iterate and fix them
4. Continue until sparse passes or no more improvements possible

## Note
Simple fixes have already been applied by scripts.
Focus on the remaining issues that require code understanding.
"""

    @classmethod
    def get_sparse_fix_system_prompt(cls) -> str:
        return """
# System Prompt

You will receive a patch diff, its commit text, and remaining sparse issues.
Script-based fixes have already been applied for simple issues.

Use the read-only tools to explore the kernel source as needed, then use
write_file_str (preferred) or write_file to apply the corrections.

**CRITICAL**: After making changes, use the `run_sparse` tool to verify 
that your fixes actually resolved the issues. This is a self-correction loop.

Sparse is a semantic checker for C programs that finds possible coding faults:
- Type mismatches and casting issues
- Null pointer dereferences
- Uninitialized variables
- Endianness issues (__le32, __be32, etc.)
- Address space annotations (__user, __kernel, __iomem, etc.)
- Lock context issues
- Symbol visibility issues (static vs extern)

## Rules

- Prefer write_file_str (exact-text match) over write_file (line range).
- Make small, targeted changes — one logical fix per tool call.
- **Always verify** your fixes with `run_sparse` after making changes.
- If sparse still reports issues, analyze and fix them iteratively.
- Only change lines necessary to address the sparse issues.
- Do not redesign or extend the patch beyond what sparse requires.
- Do not revert or remove the patch's primary contribution.
- Follow Linux kernel coding style precisely.
- Use only ASCII characters.

## Self-Correction Loop

1. Make a fix using write_file_str/write_file
2. Run `run_sparse` to verify
3. If issues remain:
   - Analyze the remaining issues
   - Make additional fixes
   - Verify again with `run_sparse`
4. Repeat until sparse passes or no more improvements possible

## Common Sparse Fixes

**Type casting:**
Add proper casts for type mismatches (e.g., `(void __user *)` for user pointers).

**Endianness annotations:**
Use __le32, __be32, etc. for endian-specific types.
Use cpu_to_le32(), le32_to_cpu(), etc. for conversions.

**Address space annotations:**
- __user: User space pointers
- __kernel: Kernel space pointers  
- __iomem: I/O memory pointers
- __percpu: Per-CPU variables

**Static declarations:**
Add 'static' keyword for functions/variables used only in one file.

**NULL pointer checks:**
Add NULL checks before dereferencing pointers.

## Important

- Make minimal changes to fix only the sparse issues
- Preserve the patch's functionality and intent
- Do not introduce new sparse warnings
- **Verify every fix** with the run_sparse tool
- If unsure, make no changes to that specific issue
- Understand the context before making type/annotation changes
"""

    def __init__(self, patch_review, review_result: str):
        """Initialize with custom tools for sparse verification and RAG."""
        super().__init__(patch_review, review_result)
        
        # RAG will be initialized in context manager during run()
        self.rag = None

    @classmethod
    def _strip_trailers(cls, msg: str) -> str:
        """Drop attribution and routing trailers from a commit message."""
        stripped_trailers = (
            "co-authored-by",
            "signed-off-by",
            "reviewed-by",
            "acked-by",
            "tested-by",
            "cc",
            "change-id",
        )
        kept = []
        for line in msg.splitlines():
            lower = line.strip().lower()
            if any(lower.startswith(f"{t}:") for t in stripped_trailers):
                continue
            kept.append(line)
        while kept and not kept[-1].strip():
            kept.pop()
        return "\n".join(kept) + "\n"

    def _apply_script_fixes(self) -> bool:
        """Apply script-based fixes to the working tree before AI processing."""
        kernel_dir = str(self.patch_review.docker_manager.kernel_dir)
        changes_made = False

        proc = self.patch_review.docker_manager.run_command(
            ["git", "diff", "--name-only", "HEAD~1"], cwd=kernel_dir
        )
        stdout, _ = proc.communicate()
        if proc.returncode != 0:
            self.logger.warning("Failed to get modified files")
            return False

        # stdout may already be a str depending on DockerManager; handle both
        if isinstance(stdout, bytes):
            lines = stdout.decode().splitlines()
        else:
            lines = str(stdout).splitlines()

        modified_files = [f.strip() for f in lines if f.strip()]
        
        for file_path in modified_files:
            if not file_path.endswith(('.c', '.h')):
                continue
                
            full_path = os.path.join(kernel_dir, file_path)
            if not os.path.exists(full_path):
                continue
                
            try:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                original_content = content
                content = self._fix_simple_static_declarations(content)
                
                if content != original_content:
                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    changes_made = True
                    self.logger.info(f"Applied script fixes to {file_path}")
                    
            except Exception as e:
                self.logger.warning(f"Error applying script fixes to {file_path}: {e}")
                continue

        if changes_made:
            proc = self.patch_review.docker_manager.run_command(
                ["git", "add", "-u"], cwd=kernel_dir
            )
            proc.communicate()
            
            proc = self.patch_review.docker_manager.run_command(
                ["git", "commit", "--amend", "--no-edit"], cwd=kernel_dir
            )
            proc.communicate()
            
            self.logger.info("Committed script-based fixes")

        return changes_made

    def _fix_simple_static_declarations(self, content: str) -> str:
        """Add static keyword to obvious cases of file-local functions."""
        lines = content.split('\n')
        fixed_lines = []
        
        for i, line in enumerate(lines):
            if (re.match(r'^\w+\s+\w+_(?:helper|internal|local|impl)\s*\(', line) and
                'static' not in line and 'extern' not in line):
                line = 'static ' + line
                self.logger.debug(f"Added static to line {i+1}")
            
            fixed_lines.append(line)
        
        return '\n'.join(fixed_lines)

    def run(self) -> str:
        """Run the AI sparse fixer with verification loop."""
        sparse_output = self.review_result

        if not sparse_output or sparse_output.strip() == "No issues found.":
            self.logger.debug(
                "Sparse found no actionable issues; skipping patch fix."
            )
            return ""

        # Stage 1: Apply script-based fixes
        self.logger.info("Stage 1: Applying script-based fixes...")
        script_fixes_applied = self._apply_script_fixes()
        
        if script_fixes_applied:
            self.logger.info("Script-based fixes applied successfully")
            remaining_issues = sparse_output
        else:
            self.logger.info("No script-based fixes needed")
            remaining_issues = sparse_output

        # Get current diff after script fixes
        kernel_dir = str(self.patch_review.docker_manager.kernel_dir)
        proc = self.patch_review.docker_manager.run_command(
            ["git", "format-patch", "-1", "--stdout", "HEAD"],
            cwd=kernel_dir
        )
        current_diff, _ = proc.communicate()
        if proc.returncode == 0:
            current_diff = current_diff
        else:
            current_diff = self.patch_review.diff

        # Stage 2: Use AI with verification loop and RAG context
        self.logger.info("Stage 2: Using AI with verification loop and RAG context...")
        
        # Initialize RAG with context manager (if available)
        rag_manager = None
        if RAG_AVAILABLE and KernelDocRAG:
            try:
                rag_manager = KernelDocRAG(kernel_dir, logger=self.logger)
                rag_manager.__enter__()
            except Exception as e:
                self.logger.warning(f"Failed to initialize RAG system: {e}")
                rag_manager = None
        else:
            self.logger.warning("RAG system not available (missing chromadb or litellm)")
        
        try:
            # Extract issue types from sparse output
            issue_types = self._extract_sparse_issue_types(remaining_issues)
            
            # Get relevant documentation context using RAG
            rag_context = ""
            if rag_manager and issue_types:
                rag_context = rag_manager.get_sparse_guidelines(issue_types)
            
            formatted_prompt = self.SPARSE_FIX_PROMPT_TEMPLATE.format(
                commit_text=self.patch_review.commit.message,
                diff=current_diff,
                sparse_issues=remaining_issues,
            )
            
            # Append RAG context to prompt
            if rag_context:
                formatted_prompt += f"\n\n{rag_context}"

            self.logger.debug(f"Formatted prompt for sparse fix:\n{formatted_prompt}")

            messages = [
                {"role": "system", "content": self.get_sparse_fix_system_prompt()},
                {"role": "user", "content": formatted_prompt},
            ]
            final_response = self.agent.run_agent_loop(messages)
            self.logger.debug(f"Sparse-fix agent final response: {final_response!r}")
        finally:
            if rag_manager:
                rag_manager.__exit__(None, None, None)

        try:
            patch_fix = self._generate_git_patch()
        except Exception as e:
            self.logger.warning(f"Failed to generate sparse patch fix: {e}")
            return ""

        return patch_fix
    
    def _extract_sparse_issue_types(self, sparse_output: str) -> List[str]:
        """
        Extract issue types from sparse output.
        
        Args:
            sparse_output: Sparse error/warning output
            
        Returns:
            List of issue type strings
        """
        issue_types = []
        
        for line in sparse_output.split('\n'):
            line_lower = line.lower()
            if 'address space' in line_lower or '__user' in line_lower or '__iomem' in line_lower:
                issue_types.append('address space annotations')
            if 'endian' in line_lower or '__le' in line_lower or '__be' in line_lower:
                issue_types.append('endianness')
            if 'static' in line_lower or 'symbol' in line_lower:
                issue_types.append('static declaration')
            if 'context' in line_lower or 'lock' in line_lower:
                issue_types.append('lock context')
            if 'cast' in line_lower or 'type' in line_lower:
                issue_types.append('type casting')
        
        # Return unique issue types
        return list(set(issue_types))
