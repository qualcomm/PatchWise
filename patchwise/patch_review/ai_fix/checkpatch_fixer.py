# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Checkpatch error fixer using AI with targeted file edits.

This fixer applies script-based fixes first, then uses AI with verification tools.
Includes RAG-based retrieval of kernel documentation for enhanced context.
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List

from patchwise.patch_review.ai_fix import AiFix
from patchwise.patch_review.static_analysis.checkpatch import Checkpatch
from patchwise.patch_review.decorators import register_fix

try:
    from patchwise.patch_review.ai_fix.kernel_docs_rag import KernelDocRAG
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False
    KernelDocRAG = None


@register_fix(Checkpatch)
class CheckpatchFixer(AiFix):
    TRAILER_PREFIXES_TO_PRESERVE = (
        "Signed-off-by:",
        "Co-authored-by:",
        "Reviewed-by:",
        "Acked-by:",
        "Tested-by:",
        "Cc:",
    )

    # checkpatch reports file:line, so edit and re-verify; no navigation needed.
    FIX_TOOLS = ["read_file", "run_checkpatch", "write_file_str", "write_file"]

    """AI-powered checkpatch fixer based on checkpatch findings.

    This fixer uses a two-stage approach:
    1. Apply script-based fixes for common issues (whitespace, SPDX, etc.)
    2. Use AI with write_file_str/write_file tools AND verification tools
    
    The AI can run checkpatch to verify fixes, enabling self-correction.
    
    The AI edits files directly inside the Docker container. Those working-tree 
    edits are then folded into HEAD via ``git commit --amend`` and emitted as 
    an mbox patch via ``git format-patch``.

    Returns patch fix output.
    """

    CHECKPATCH_FIX_PROMPT_TEMPLATE = """
# User Prompt

The following patch diff has checkpatch errors and warnings that need to be fixed.
Script-based fixes have already been applied for simple issues.
Use the write tools to apply fixes for the remaining checkpatch issues
directly to the source files in the kernel tree.

**IMPORTANT**: After making changes, use the `run_checkpatch` tool to verify 
that the issues are fixed. If issues remain, iterate and fix them.

## Commit text

{commit_text}

## Current patch diff (after script fixes)

```diff
{diff}
```

## Remaining checkpatch issues to fix

{checkpatch_issues}

## Available Tools

1. **write_file_str** / **write_file**: Edit source files
2. **run_checkpatch**: Verify your fixes by running checkpatch
3. **read_file**: Read file contents to understand context

## Workflow

1. Make targeted edits to fix issues
2. Run `run_checkpatch` to verify fixes
3. If issues remain, iterate and fix them
4. Continue until checkpatch passes or no more improvements possible

## Note
Simple whitespace and formatting issues have already been fixed by scripts.
Focus on the remaining issues that require code understanding.
"""

    @classmethod
    def get_checkpatch_fix_system_prompt(cls) -> str:
        return """
# System Prompt

You will receive a patch diff, its commit text, and remaining checkpatch issues.
Script-based fixes have already been applied for simple issues.

Use the read-only tools to explore the kernel source as needed, then use
write_file_str (preferred) or write_file to apply the corrections.

**CRITICAL**: After making changes, use the `run_checkpatch` tool to verify 
that your fixes actually resolved the issues. This is a self-correction loop.

## Rules

- Prefer write_file_str (exact-text match) over write_file (line range).
- Make small, targeted changes — one logical fix per tool call.
- **Always verify** your fixes with `run_checkpatch` after making changes.
- If checkpatch still reports issues, analyze and fix them iteratively.
- Only change lines necessary to address the checkpatch issues.
- Do not redesign or extend the patch beyond what checkpatch requires.
- Do not revert or remove the patch's primary contribution.
- Follow Linux kernel coding style precisely (Documentation/process/coding-style.rst).
- Use only ASCII characters.

## Self-Correction Loop

1. Make a fix using write_file_str/write_file
2. Run `run_checkpatch` to verify
3. If issues remain:
   - Analyze the remaining issues
   - Make additional fixes
   - Verify again with `run_checkpatch`
4. Repeat until checkpatch passes or no more improvements possible

## Focus Areas (scripts already handled basic issues)

- Complex line length issues requiring code restructuring
- Function/macro refactoring for style compliance
- Logic-dependent fixes (e.g., replacing hardcoded names with __func__)
- Context-dependent formatting issues
- Issues requiring understanding of surrounding code

## Important

- Make minimal changes to fix only the checkpatch issues
- Preserve the patch's functionality and intent
- Do not introduce new checkpatch errors
- **Verify every fix** with the run_checkpatch tool
- If unsure, make no changes to that specific issue
"""

    def __init__(self, patch_review, review_result: str):
        """Initialize with custom tools for checkpatch verification and RAG."""
        super().__init__(patch_review, review_result)
        
        # RAG will be initialized in context manager during run()
        self.rag = None


    def _apply_script_fixes(self) -> bool:
        """Apply script-based fixes to the working tree before AI processing.
        
        This applies simple, deterministic fixes that don't require AI:
        - Trailing whitespace removal
        - DOS line ending conversion
        - Space before tab fixes
        - Basic SPDX license fixes
        - checkpatch.pl --fix if available
        
        Returns:
            True if any fixes were applied, False otherwise
        """
        kernel_dir = str(self.patch_review.docker_manager.kernel_dir)
        changes_made = False

        # Get list of modified files from the patch
        proc = self.patch_review.docker_manager.run_command(
            ["git", "diff", "--name-only", "HEAD~1"], cwd=kernel_dir
        )
        stdout, _ = proc.communicate()
        if proc.returncode != 0:
            self.logger.warning("Failed to get modified files")
            return False

        modified_files = [f.strip() for f in stdout.splitlines() if f.strip()]
        self.logger.info(f"Found {len(modified_files)} modified files to process: {modified_files}")
        
        for file_path in modified_files:
            try:
                # Construct full container path (absolute path inside container)
                full_container_path = os.path.join(kernel_dir, file_path)
                
                self.logger.debug(f"Reading {file_path} from container (full path: {full_container_path})...")
                # Read file from container using docker_manager.read_file() with absolute path
                content = self.patch_review.docker_manager.read_file(full_container_path)
                
                if not content or not isinstance(content, str):
                    self.logger.warning(f"Failed to read {file_path} from container (got {type(content).__name__})")
                    continue
                
                self.logger.debug(f"Successfully read {file_path}, size: {len(content)} bytes")
                original_content = content
                
                # Fix trailing whitespace
                content = self._fix_trailing_whitespace(content)
                
                # Fix DOS line endings
                content = content.replace('\r\n', '\n').replace('\r', '\n')
                
                # Fix space before tab
                content = self._fix_space_before_tab(content)
                
                # Fix SPDX license (basic cases)
                content = self._fix_spdx_license(content, file_path)
                
                if content != original_content:
                    self.logger.debug(f"Content changed for {file_path}, writing back to container...")
                    # Write file back to container using docker_manager.write_file() with absolute path
                    success = self.patch_review.docker_manager.write_file(full_container_path, content)
                    
                    if success:
                        changes_made = True
                        self.logger.info(f"✓ Applied script fixes to {file_path} (wrote {len(content)} bytes)")
                    else:
                        self.logger.warning(f"✗ Failed to write {file_path} to container")
                else:
                    self.logger.debug(f"No changes needed for {file_path}")
                    
            except Exception as e:
                self.logger.warning(f"Error applying script fixes to {file_path}: {e}")
                continue

        # Try checkpatch.pl --fix if available
        self.logger.info("Attempting checkpatch.pl --fix-inplace...")
        if self._try_checkpatch_fix(kernel_dir):
            changes_made = True
            self.logger.info("✓ checkpatch.pl --fix-inplace completed successfully")
        else:
            self.logger.debug("checkpatch.pl --fix-inplace not available or produced no fixes")

        # Commit the script fixes if any were made
        if changes_made:
            self.logger.info("Committing script-based fixes...")
            proc = self.patch_review.docker_manager.run_command(
                ["git", "add", "-u"], cwd=kernel_dir
            )
            stdout_add, stderr_add = proc.communicate()
            if proc.returncode != 0:
                self.logger.warning(f"git add -u failed (rc={proc.returncode}): {stderr_add}")
            else:
                self.logger.debug("git add -u successful")
            
            proc = self.patch_review.docker_manager.run_command(
                ["git", "commit", "--amend", "--no-edit"], cwd=kernel_dir
            )
            stdout_commit, stderr_commit = proc.communicate()
            if proc.returncode != 0:
                self.logger.warning(f"git commit --amend failed (rc={proc.returncode}): {stderr_commit}")
            else:
                self.logger.info("✓ Successfully committed script-based fixes")
        else:
            self.logger.info("No script-based changes to commit")

        return changes_made

    def _fix_trailing_whitespace(self, content: str) -> str:
        """Remove trailing whitespace from all lines."""
        lines = content.split('\n')
        fixed_lines = [line.rstrip() for line in lines]
        return '\n'.join(fixed_lines)

    def _fix_space_before_tab(self, content: str) -> str:
        """Fix space before tab issues."""
        lines = content.split('\n')
        fixed_lines = []
        for line in lines:
            while line.startswith(' \t'):
                line = line.replace(' \t', '\t', 1)
            fixed_lines.append(line)
        return '\n'.join(fixed_lines)

    def _fix_spdx_license(self, content: str, file_path: str) -> str:
        """Fix SPDX license identifier format based on file type."""
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            if 'SPDX-License-Identifier' not in line:
                continue
                
            if file_path.endswith('.c'):
                if line.strip().startswith('/*') and 'SPDX-License-Identifier' in line:
                    match = re.search(r'SPDX-License-Identifier:\s*([^*\s]+)', line)
                    if match:
                        license_id = match.group(1)
                        lines[i] = f'// SPDX-License-Identifier: {license_id}'
                        
            elif file_path.endswith('.h'):
                if line.strip().startswith('//') and 'SPDX-License-Identifier' in line:
                    match = re.search(r'SPDX-License-Identifier:\s*(.+)', line)
                    if match:
                        license_id = match.group(1).strip()
                        lines[i] = f'/* SPDX-License-Identifier: {license_id} */'
        
        return '\n'.join(lines)

    def _try_checkpatch_fix(self, kernel_dir: str) -> bool:
        """Try to apply checkpatch.pl --fix entirely inside the container.

        This avoids creating host-side temporary files that are not visible
        inside Docker. We run a shell pipeline that:
        - Checks if scripts/checkpatch.pl exists and is executable
        - Creates a temporary patch file inside the container
        - Runs checkpatch.pl --fix-inplace on it
        - Applies the generated .EXPERIMENTAL-checkpatch-fixes if present
        - Cleans up temporary files
        """
        try:
            cmd = [
                "sh",
                "-c",
                (
                    "set -e; "
                    "CHECKPATCH=scripts/checkpatch.pl; "
                    "if [ ! -x \"$CHECKPATCH\" ]; then exit 1; fi; "
                    "TMP=$(mktemp /tmp/checkpatch.XXXXXX.patch); "
                    "git format-patch -1 --stdout HEAD >\"$TMP\"; "
                    "\"$CHECKPATCH\" --fix-inplace --no-summary \"$TMP\" || true; "
                    "FIXED=\"$TMP.EXPERIMENTAL-checkpatch-fixes\"; "
                    "if [ -f \"$FIXED\" ]; then "
                    "git apply \"$FIXED\"; "
                    "rm -f \"$FIXED\"; "
                    "fi; "
                    "rm -f \"$TMP\""
                ),
            ]
            proc = self.patch_review.docker_manager.run_command(cmd, cwd=kernel_dir)
            proc.communicate()
            if proc.returncode != 0:
                # Either checkpatch.pl not found or format-patch/apply failed
                self.logger.debug(
                    f"checkpatch --fix-inplace pipeline failed with rc={proc.returncode}"
                )
                return False

            self.logger.info(
                "Applied checkpatch.pl --fix inside container (if fixes were produced)"
            )
            return True
        except Exception as e:
            self.logger.debug(f"checkpatch --fix not available or failed: {e}")
            return False

    def _has_commit_message_issues(self, checkpatch_output: str) -> bool:
        """Check if checkpatch output contains commit message warnings."""
        return "COMMIT_MESSAGE" in checkpatch_output or "COMMIT_LOG" in checkpatch_output

    def _extract_preserved_trailers(self, commit_msg: str) -> list[str]:
        """Extract sign-off / attribution trailers we must preserve."""
        trailers: list[str] = []
        for line in commit_msg.splitlines():
            stripped = line.strip()
            if any(stripped.startswith(p) for p in self.TRAILER_PREFIXES_TO_PRESERVE):
                trailers.append(line)
        return trailers

    def _restore_trailers_if_missing(self, preserved_trailers: list[str]) -> None:
        """Ensure preserved trailers are present in the current commit message.

        This compensates for base-class _strip_trailers() stripping trailers.
        We re-attach any sign-off style lines that are missing, so we don't
        lose Signed-off-by, Co-authored-by, etc.
        """
        if not preserved_trailers:
            return

        kernel_dir = str(self.patch_review.docker_manager.kernel_dir)

        # Read current commit message
        proc = self.patch_review.docker_manager.run_command(
            ["git", "log", "-1", "--format=%B"],
            cwd=kernel_dir,
        )
        current_msg_bytes, stderr = proc.communicate()
        if proc.returncode != 0:
            self.logger.warning(f"Failed to get current commit message for trailer restore: {stderr}")
            return

        current_msg = (
            current_msg_bytes.decode("utf-8")
            if isinstance(current_msg_bytes, bytes)
            else current_msg_bytes
        )

        current_lines = current_msg.splitlines()
        # Track which trailers are already present (string match)
        existing = set(line.strip() for line in current_lines)

        to_append: list[str] = []
        for t in preserved_trailers:
            if t.strip() not in existing:
                to_append.append(t)

        if not to_append:
            # Nothing to restore
            return

        # Build new message: original current_msg (without extra trailing blank lines)
        # plus missing trailers at the end.
        while current_lines and not current_lines[-1].strip():
            current_lines.pop()
        new_lines = current_lines + to_append
        new_msg = "\n".join(new_lines).rstrip() + "\n"

        self.logger.debug(
            f"Restoring {len(to_append)} preserved trailers into commit message"
        )

        proc = self.patch_review.docker_manager.run_interactive_command(
            ["git", "commit", "--amend", "-F", "-"],
            cwd=kernel_dir,
        )
        _stdout, stderr = proc.communicate(input=new_msg)
        if proc.returncode != 0:
            self.logger.warning(f"Failed to restore trailers on commit message: {stderr}")

    def _fix_commit_message(self, checkpatch_output: str) -> bool:
        """Use LLM to fix commit message issues.
        
        Returns:
            True if commit message was fixed, False otherwise
        """
        kernel_dir = str(self.patch_review.docker_manager.kernel_dir)
        
        # Get current commit message
        proc = self.patch_review.docker_manager.run_command(
            ["git", "log", "-1", "--format=%B"],
            cwd=kernel_dir
        )
        current_message_bytes, _ = proc.communicate()
        if proc.returncode != 0:
            self.logger.warning("Failed to get current commit message")
            return False
        
        # Decode to string
        current_message = current_message_bytes.decode('utf-8') if isinstance(current_message_bytes, bytes) else current_message_bytes
        
        # Get the diff to provide context
        proc = self.patch_review.docker_manager.run_command(
            ["git", "show", "--format=", "HEAD"],
            cwd=kernel_dir
        )
        diff_content_bytes, _ = proc.communicate()
        
        # Decode to string
        diff_content = diff_content_bytes.decode('utf-8') if isinstance(diff_content_bytes, bytes) else diff_content_bytes
        
        # Create prompt for LLM to fix commit message
        prompt = f"""Fix the following commit message to address checkpatch warnings.

Current commit message:
```
{current_message}
```

Checkpatch warnings:
```
{checkpatch_output}
```

Patch diff (for context):
```diff
{diff_content[:2000]}  # First 2000 chars for context
```

Please provide a corrected commit message that:
1. Follows Linux kernel commit message guidelines
2. Addresses all checkpatch warnings
3. Maintains the original intent and technical accuracy
4. Uses proper imperative mood
5. Includes appropriate subsystem prefix
6. Has a clear, concise subject line (50-75 chars)
7. Includes a detailed body explaining what and why (if needed)

Provide ONLY the corrected commit message, nothing else."""

        try:
            # Use the agent's LLM to generate fixed commit message
            import litellm
            
            self.logger.debug(f"Calling LLM with prompt length: {len(prompt)}")
            response = litellm.completion(
                model=self.agent.model,
                messages=[
                    {"role": "system", "content": "You are an expert in Linux kernel development and commit message formatting."},
                    {"role": "user", "content": prompt}
                ],
                api_base=self.agent.api_base if hasattr(self.agent, 'api_base') else None,
            )
            
            fixed_message = response.choices[0].message.content.strip()
            self.logger.debug(f"LLM returned message type: {type(fixed_message)}, length: {len(fixed_message)}")
            
            # Remove markdown code blocks if present
            if fixed_message.startswith("```"):
                lines = fixed_message.split('\n')
                fixed_message = '\n'.join(lines[1:-1]) if len(lines) > 2 else fixed_message
                self.logger.debug("Removed markdown code blocks")
            
            # Ensure fixed_message is a string (subprocess will encode it)
            self.logger.debug(f"Before passing to subprocess - type: {type(fixed_message)}")
            if isinstance(fixed_message, bytes):
                fixed_message = fixed_message.decode('utf-8')
                self.logger.debug("Decoded bytes to string")
            
            # Update commit message (pass string, subprocess will encode it)
            self.logger.debug("Running git commit --amend")
            proc = self.patch_review.docker_manager.run_interactive_command(
                ["git", "commit", "--amend", "-F", "-"],
                cwd=kernel_dir,
            )
            _, stderr = proc.communicate(input=fixed_message)
            
            if proc.returncode == 0:
                self.logger.info("Successfully fixed commit message")
                return True
            else:
                self.logger.warning(f"Failed to update commit message: {stderr}")
                return False
                
        except Exception as e:
            import traceback
            self.logger.error(f"Failed to fix commit message with LLM: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def run(self) -> str:
        """Run the AI checkpatch fixer with verification loop."""
        checkpatch_output = self.review_result

        # Capture original commit message trailers up front so we can
        # restore them after AI/script edits and before emitting the
        # final patch. This avoids losing Signed-off-by, Co-authored-by,
        # etc. even though the base AiFix._strip_trailers may strip them.
        kernel_dir = str(self.patch_review.docker_manager.kernel_dir)
        preserved_trailers: list[str] = []
        try:
            proc = self.patch_review.docker_manager.run_command(
                ["git", "log", "-1", "--format=%B"],
                cwd=kernel_dir,
            )
            orig_msg_bytes, stderr = proc.communicate()
            if proc.returncode == 0:
                orig_msg = (
                    orig_msg_bytes.decode("utf-8")
                    if isinstance(orig_msg_bytes, bytes)
                    else orig_msg_bytes
                )
                preserved_trailers = self._extract_preserved_trailers(orig_msg)
            else:
                self.logger.warning(f"Failed to read original commit message for trailer capture: {stderr}")
        except Exception as e:
            self.logger.warning(f"Error capturing original commit trailers: {e}")

        if not checkpatch_output or checkpatch_output.strip() == "No issues found.":
            self.logger.debug(
                "Checkpatch found no actionable issues; skipping patch fix."
            )
            return ""

        # Stage 0: Fix commit message issues if present
        if self._has_commit_message_issues(checkpatch_output):
            self.logger.info("Stage 0: Fixing commit message issues...")
            commit_msg_fixed = self._fix_commit_message(checkpatch_output)
            if commit_msg_fixed:
                self.logger.info("Commit message fixed successfully")

        # Stage 1: Apply script-based fixes
        self.logger.info("Stage 1: Applying script-based fixes...")
        script_fixes_applied = self._apply_script_fixes()
        
        if script_fixes_applied:
            self.logger.info("Script-based fixes applied successfully")
            remaining_issues = checkpatch_output
        else:
            self.logger.info("No script-based fixes needed")
            remaining_issues = checkpatch_output

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
                # Use host-side repo working directory for documentation RAG,
                # not the container kernel path.
                host_repo_dir = str(self.patch_review.repo.working_dir)
                rag_manager = KernelDocRAG(host_repo_dir, logger=self.logger)
                rag_manager.__enter__()
            except Exception as e:
                self.logger.warning(f"Failed to initialize RAG system: {e}")
                rag_manager = None
        else:
            self.logger.warning("RAG system not available (missing chromadb or litellm)")
        
        try:
            # Extract issue types from checkpatch output
            issue_types = self._extract_checkpatch_issue_types(remaining_issues)
            
            # Get relevant documentation context using RAG
            rag_context = ""
            if rag_manager and issue_types:
                rag_context = rag_manager.get_checkpatch_guidelines(issue_types)
            
            formatted_prompt = self.CHECKPATCH_FIX_PROMPT_TEMPLATE.format(
                commit_text=self.patch_review.commit.message,
                diff=current_diff,
                checkpatch_issues=remaining_issues,
            )
            
            # Append RAG context to prompt
            if rag_context:
                formatted_prompt += f"\n\n{rag_context}"

            self.logger.debug(f"Formatted prompt for checkpatch fix:\n{formatted_prompt}")

            messages = [
                {"role": "system", "content": self.get_checkpatch_fix_system_prompt()},
                {"role": "user", "content": formatted_prompt},
            ]
            final_response = self.agent.run_agent_loop(
                messages, allowed_tools=self.FIX_TOOLS
            )
            self.logger.debug(f"Checkpatch-fix agent final response: {final_response!r}")
        finally:
            if rag_manager:
                rag_manager.__exit__(None, None, None)

        try:
            patch_fix = self._generate_git_patch()
        except Exception as e:
            self.logger.warning(f"Failed to generate checkpatch patch fix: {e}")
            return ""

        return patch_fix
    
    def _extract_checkpatch_issue_types(self, checkpatch_output: str) -> List[str]:
        """
        Extract issue types from checkpatch output.
        
        Args:
            checkpatch_output: Checkpatch error/warning output
            
        Returns:
            List of issue type strings
        """
        issue_types = []
        
        for line in checkpatch_output.split('\n'):
            line_lower = line.lower()
            if 'line' in line_lower and ('length' in line_lower or 'long' in line_lower):
                issue_types.append('line length')
            if 'spdx' in line_lower:
                issue_types.append('SPDX license')
            if 'whitespace' in line_lower or 'trailing' in line_lower:
                issue_types.append('whitespace')
            if 'brace' in line_lower:
                issue_types.append('brace placement')
            if 'macro' in line_lower:
                issue_types.append('macro definition')
            if 'signed-off-by' in line_lower:
                issue_types.append('signed-off-by')
        
        # Return unique issue types
        return list(set(issue_types))
