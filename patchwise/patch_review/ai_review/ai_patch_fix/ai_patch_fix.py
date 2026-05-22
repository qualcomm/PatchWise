# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from typing import Any, Dict, List, Optional

from patchwise.patch_review.decorators import register_llm_review, register_long_review

from patchwise.patch_review.ai_review.ai_code_review import AiCodeReview
from patchwise.patch_review.ai_review.ai_patch_fix.tool_definitions import TOOLS


@register_llm_review
@register_long_review
class AiPatchFix(AiCodeReview):
    """AI-powered patch fix based on AI code review findings.

    The AI uses the write_file_str / write_file tools to edit files directly
    inside the Docker container. Those working-tree edits are then folded
    into HEAD via ``git commit --amend`` and emitted as an mbox patch via
    ``git format-patch``.

    Returns a tuple (code_review_output, patch_fix_output).
    """

    PATCH_SUGGEST_PROMPT_TEMPLATE = """
# User Prompt

The following patch diff has been reviewed by a Linux kernel maintainer.
Use the write tools to apply fixes that address the reviewer's feedback
directly to the source files in the kernel tree.

## Commit text

{commit_text}

## Original patch diff

```diff
{diff}
```

## Code review feedback

{code_review}
"""

    @classmethod
    def get_patch_fix_system_prompt(cls) -> str:
        return """
# System Prompt

You will receive a patch diff, its commit text, and code review feedback.
Use the read-only tools to explore the kernel source as needed, then use
write_file_str (preferred) or write_file to apply the corrections.

The review identifies concrete problems. Your job is to address each one
with a targeted edit.

## Rules

- Prefer write_file_str (exact-text match) over write_file (line range).
- Make small, targeted changes — one logical fix per tool call.
- Only change lines necessary to address the review feedback.
- Do not redesign or extend the patch beyond what the review requests.
- Do not revert or remove the patch's primary contribution. If the review
  concludes the patch is not valid, make no edits — leave the working tree
  unchanged.
- Follow Linux kernel coding style precisely.
- Use only ASCII characters.
"""

    def get_tools(self) -> Optional[List[Dict[str, Any]]]:
        parent_tools = super().get_tools() or []
        return parent_tools + TOOLS

    def dispatch_tool(self, name: str, args: dict) -> dict:
        write_tools = {
            "write_file": self._tool_write_file,
            "write_file_str": self._tool_write_file_str,
        }
        tool_fn = write_tools.get(name)
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

    def _container_path(self, file: str) -> str:
        return f"{self.docker_manager.kernel_dir}/{file}"

    def _read(self, container_path: str) -> str:
        text = self.docker_manager.read_file(container_path)
        if text is False:
            raise RuntimeError(f"Failed to read {container_path} from container")
        return text

    def _write(self, container_path: str, content: str) -> None:
        if not self.docker_manager.write_file(container_path, content):
            raise RuntimeError(f"Failed to write {container_path} in container")

    def _tool_write_file_str(
        self, file: str, old_content: str, new_content: str
    ) -> dict:
        """Replace old_content with new_content in a container file (exact match)."""
        container_path = self._container_path(file)
        existing = self._read(container_path)

        count = existing.count(old_content)
        if count == 0:
            return {"ok": False, "error": "old_content not found in file"}
        if count > 1:
            return {
                "ok": False,
                "error": f"old_content matches {count} times; be more specific",
            }

        self._write(container_path, existing.replace(old_content, new_content, 1))
        return {"ok": True}

    def _tool_write_file(self, file: str, start: int, end: int, content: str) -> dict:
        """Replace lines [start, end] (1-based, inclusive) in a container file."""
        container_path = self._container_path(file)
        lines = self._read(container_path).splitlines(keepends=True)

        if start < 1:
            return {"ok": False, "error": f"start ({start}) must be >= 1"}
        if end < start:
            return {"ok": False, "error": f"end ({end}) must be >= start ({start})"}
        if end > len(lines):
            return {
                "ok": False,
                "error": f"end ({end}) exceeds file length ({len(lines)} lines)",
            }

        new_lines = [l + "\n" for l in content.splitlines(keepends=False)]
        lines[start - 1 : end] = new_lines
        self._write(container_path, "".join(lines))
        return {"ok": True}

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
        # Strip trailing new lines
        while kept and not kept[-1].strip():
            kept.pop()
        return "\n".join(kept) + "\n"

    def _generate_git_patch(self) -> str:
        """Produce an mbox-format patch reflecting the AI's working-tree edits.

        The AI writes to the working tree via write_file / write_file_str.
        ``git format-patch`` only sees committed history, so we must first
        fold those working-tree edits into HEAD (amending the original patch
        commit) before formatting. Returns an empty string if the AI made
        no changes to the tree.
        """
        kernel_dir = str(self.docker_manager.kernel_dir)

        proc = self.docker_manager.run_command(
            ["git", "diff", "--quiet", "HEAD"], cwd=kernel_dir
        )
        proc.communicate()
        if proc.returncode == 0:
            self.logger.debug("No working-tree changes from AI; no patch fix.")
            return ""

        proc = self.docker_manager.run_command(
            ["git", "log", "-1", "--format=%B"], cwd=kernel_dir
        )
        orig_msg, stderr = proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git log failed: {stderr}")
        new_msg = self._strip_trailers(orig_msg)

        proc = self.docker_manager.run_interactive_command(
            ["git", "commit", "-a", "--amend", "-F", "-"],
            cwd=kernel_dir,
        )
        _stdout, stderr = proc.communicate(input=new_msg)
        if proc.returncode != 0:
            raise RuntimeError(f"git commit --amend failed: {stderr}")

        proc = self.docker_manager.run_command(
            [
                "git",
                "format-patch",
                "HEAD~1",
                "--stdout",
            ],
            cwd=kernel_dir,
        )
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git format-patch failed: {stderr}")
        return stdout.strip()

    def run(self) -> tuple[str, str]:
        """Run the AI code review, then generate a patch fix.

        Returns:
            A tuple of (code_review_output, patch_fix_output) where
            patch_fix_output is an mbox-format patch produced by amending
            HEAD with the AI's working-tree edits and running
            ``git format-patch HEAD~1 --stdout``, or an empty string when
            no changes were made.
        """
        code_review_output = super().run()

        if not code_review_output or code_review_output.strip() == "No issues found.":
            self.logger.debug(
                "AiCodeReview found no actionable issues; skipping patch fix."
            )
            return code_review_output, ""

        formatted_prompt = self.PATCH_SUGGEST_PROMPT_TEMPLATE.format(
            commit_text=self.commit_message,
            diff=self.diff,
            code_review=code_review_output,
        )

        self.logger.debug(f"Formatted prompt for patch fix:\n{formatted_prompt}")

        messages = [
            {"role": "system", "content": self.get_patch_fix_system_prompt()},
            {"role": "user", "content": formatted_prompt},
        ]
        final_response = self.run_agent_loop(messages)
        self.logger.debug(f"Patch-fix agent final response: {final_response!r}")

        try:
            patch_fix = self._generate_git_patch()
        except Exception as e:
            self.logger.warning(f"Failed to generate patch fix: {e}")
            return code_review_output, ""

        return code_review_output, patch_fix
