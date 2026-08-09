# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Sparse error fixer using AI with targeted file edits.

This fixer applies script-based fixes first, then uses AI with verification tools.
Includes RAG-based retrieval of kernel documentation for enhanced context.
"""

import os
from typing import List

from patchwise.patch_review.ai_fix import AiFix
from patchwise.patch_review.static_analysis.sparse import Sparse
from patchwise.patch_review.decorators import register_fix
from patchwise.patch_review.ai_agent.tool_definitions import NAVIGATION_TOOLS

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
    1. Apply script-based fixes to the working tree (uncommitted).
    2. Use AI with write_file_str AND verification tools; a single
       git commit --amend at the end folds everything into HEAD.

    The AI can run sparse to verify fixes, enabling self-correction.

    The AI edits files directly inside the Docker container. Those working-tree
    edits are then folded into HEAD via ``git commit --amend`` and emitted as
    an mbox patch via ``git format-patch``.

    Returns patch fix output.
    """

    # sparse reports file:line diagnostics, so edit, re-verify, repeat.
    FIX_TOOLS = NAVIGATION_TOOLS + ["run_sparse", "write_file_str"]

    SPARSE_FIX_PROMPT_TEMPLATE = """
# User Prompt

The following patch diff has sparse warnings and errors that need to be fixed.
Script-based fixes have already been applied to the working tree.
Use the write_file_str tool to apply fixes for the remaining sparse issues
directly to the source files in the kernel tree.

**IMPORTANT**: After making changes, use the `run_sparse` tool to verify
that the issues are fixed. If issues remain, iterate and fix them.

## Commit text

{commit_text}

## Current patch diff (original commit + working-tree script fixes)

```diff
{diff}
```

## Remaining sparse issues to fix

{sparse_issues}

## Available Tools

1. **write_file_str**: Edit source files (exact-text replacement)
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
Script-based fixes have already been applied to the working tree.

Use the read-only tools to explore the kernel source as needed, then use
write_file_str to apply the corrections.

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

- Use write_file_str (exact-text match) for all source edits.
- Make small, targeted changes — one logical fix per tool call.
- **Always verify** your fixes with `run_sparse` after making changes.
- If sparse still reports issues, analyze and fix them iteratively.
- Only change lines necessary to address the sparse issues.
- Do not redesign or extend the patch beyond what sparse requires.
- Do not revert or remove the patch's primary contribution.
- Follow Linux kernel coding style precisely.
- Use only ASCII characters.

## Self-Correction Loop

1. Make a fix using write_file_str
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
        super().__init__(patch_review, review_result)
        self.rag = None

    def _apply_script_fixes(self) -> bool:
        """Write working-tree fixes without committing.

        Edits are left as uncommitted changes so that _generate_git_patch()
        can fold them together with the AI's edits in a single amend.
        Returns True if any files were modified.
        """
        kernel_dir = str(self.patch_review.docker_manager.kernel_dir)

        proc = self.patch_review.docker_manager.run_command(
            ["git", "diff", "--name-only", "HEAD~1"], cwd=kernel_dir
        )
        stdout, _ = proc.communicate()
        if proc.returncode != 0:
            self.logger.warning("Failed to get modified files")
            return False

        if isinstance(stdout, bytes):
            lines = stdout.decode().splitlines()
        else:
            lines = str(stdout).splitlines()

        modified_files = [f.strip() for f in lines if f.strip()]
        self.logger.info(f"Found {len(modified_files)} modified files to process")
        changes_made = False

        for file_path in modified_files:
            if not file_path.endswith((".c", ".h")):
                continue
            try:
                full_container_path = os.path.join(kernel_dir, file_path)
                content = self.patch_review.docker_manager.read_file(full_container_path)
                if not content or not isinstance(content, str):
                    self.logger.warning(f"Failed to read {file_path} from container")
                    continue
                # No heuristic transforms — leave all static/visibility fixes
                # to the AI so it can act on explicit sparse diagnostics.
            except Exception as e:
                self.logger.warning(f"Error processing {file_path}: {e}")

        return changes_made

    def run(self) -> str:
        """Run the AI sparse fixer with verification loop."""
        sparse_output = self.review_result

        if not sparse_output or sparse_output.strip() == "No issues found.":
            self.logger.debug("Sparse found no actionable issues; skipping patch fix.")
            return ""

        # Stage 1: Apply script-based fixes to the working tree (uncommitted).
        self.logger.info("Stage 1: Applying script-based fixes...")
        self._apply_script_fixes()

        # Build the diff shown to the AI: HEAD~1..working-tree captures both
        # the original commit and any script edits, without an intermediate amend.
        kernel_dir = str(self.patch_review.docker_manager.kernel_dir)
        proc = self.patch_review.docker_manager.run_command(
            ["git", "diff", "HEAD~1"],
            cwd=kernel_dir,
        )
        current_diff, _ = proc.communicate()
        if proc.returncode != 0 or not current_diff:
            current_diff = self.patch_review.diff

        # Stage 2: AI loop with RAG context and self-correction via run_sparse.
        self.logger.info("Stage 2: Using AI with verification loop and RAG context...")

        rag_manager = None
        if RAG_AVAILABLE and KernelDocRAG:
            try:
                host_repo_dir = str(self.patch_review.repo.working_dir)
                rag_manager = KernelDocRAG(host_repo_dir, logger=self.logger)
                rag_manager.__enter__()
            except Exception as e:
                self.logger.warning(f"Failed to initialize RAG system: {e}")

        try:
            issue_types = self._extract_sparse_issue_types(sparse_output)
            rag_context = ""
            if rag_manager and issue_types:
                rag_context = rag_manager.get_sparse_guidelines(issue_types)

            formatted_prompt = self.SPARSE_FIX_PROMPT_TEMPLATE.format(
                commit_text=self.patch_review.commit.message,
                diff=current_diff,
                sparse_issues=sparse_output,
            )
            if rag_context:
                formatted_prompt += f"\n\n{rag_context}"

            self.logger.debug(f"Formatted prompt for sparse fix:\n{formatted_prompt}")

            messages = [
                {"role": "system", "content": self.get_sparse_fix_system_prompt()},
                {"role": "user", "content": formatted_prompt},
            ]
            final_response = self.agent.run_agent_loop(
                messages, allowed_tools=self.FIX_TOOLS
            )
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
