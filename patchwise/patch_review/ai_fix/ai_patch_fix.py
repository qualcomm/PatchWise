# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause


from patchwise.patch_review.ai_fix import AiFix
from patchwise.patch_review.ai_review.ai_code_review import AiCodeReview
from patchwise.patch_review.decorators import register_fix


@register_fix(AiCodeReview)
class AiPatchFix(AiFix):
    """AI-powered patch fix based on AI code review findings.

    The AI uses the write_file_str / write_file tools to edit files directly
    inside the Docker container. Those working-tree edits are then folded
    into HEAD via ``git commit --amend`` and emitted as an mbox patch via
    ``git format-patch``.

    Returns patch fix output.
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


    def run(self) -> str:
        """Run the AI patch fix and return an mbox-format patch string.

        Returns an mbox-format patch produced by amending HEAD with the AI's
        working-tree edits and running ``git format-patch HEAD~1 --stdout``,
        or an empty string when no changes were made.
        """
        code_review_output = self.review_result

        if not code_review_output or code_review_output.strip() == "No issues found.":
            self.logger.debug(
                "AiCodeReview found no actionable issues; skipping patch fix."
            )
            return ""

        formatted_prompt = self.PATCH_SUGGEST_PROMPT_TEMPLATE.format(
            commit_text=self.patch_review.commit_message,
            diff=self.patch_review.diff,
            code_review=code_review_output,
        )

        self.logger.debug(f"Formatted prompt for patch fix:\n{formatted_prompt}")

        messages = [
            {"role": "system", "content": self.get_patch_fix_system_prompt()},
            {"role": "user", "content": formatted_prompt},
        ]
        final_response = self.agent.run_agent_loop(messages)
        self.logger.debug(f"Patch-fix agent final response: {final_response!r}")

        try:
            patch_fix = self._generate_git_patch()
        except Exception as e:
            self.logger.warning(f"Failed to generate patch fix: {e}")
            return ""

        return patch_fix
