# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from pathlib import Path
import re
import textwrap

from patchwise.patch_review.ai_agent.agent import Agent
from patchwise.patch_review.patch_review import PatchReview


class AiReview(PatchReview):

    # TODO: This messes up the formatting when AI has its own code in the response
    def format_chat_response(self, text: str) -> str:
        """
        Line wraps the given text at 75 columns but skips commit tags.
        """

        def split_text_into_paragraphs(text: str) -> list[str]:
            """
            Splits the input text into paragraphs, treating each bullet
            point line as a separate paragraph.
            """
            lines = text.split("\n")
            paragraphs = []
            current = []
            bullet_pattern = re.compile(
                r"""
                ^\s*                              # Optional leading whitespace
                (
                    [*+\->]                       # Unordered bullet characters
                    |                             # OR
                    \d+[.)-]                      # Numbered bullets like 1. or 2)
                    |                             # OR
                    \d+(\.\d+)+                   # Decimal bullets like 1.1 or 1.2.3
                )
                \s*                               # At least one space after the bullet
            """,
                re.VERBOSE,
            )

            for line in lines:
                line_stripped = line.strip()
                if (
                    line_stripped == ""
                    or line_stripped == "```"
                    or line_stripped == "'''"
                    or line_stripped == '"""'
                    or bullet_pattern.match(line_stripped) is not None
                ):
                    if len(current) > 0:
                        paragraphs.append("\n".join(current))
                        current = []
                    paragraphs.append(line)
                else:
                    current.append(line)
            if len(current) > 0:
                paragraphs.append("\n".join(current))

            return paragraphs

        def is_commit_tag(text: str) -> bool:
            """
            Checks if the given text starts with a commit tag.
            The TAGS list includes tags from the Kernel documentation
            https://www.kernel.org/doc/html/latest/process/submitting-patches.html
            and additional tags like "Change-Id".
            """
            TAGS = {
                # Upstream tags
                "Acked-by:",
                "Cc:",
                "Closes:",
                "Co-developed-by:",
                "Fixes:",
                "From:",
                "Link:",
                "Reported-by:",
                "Reviewed-by:",
                "Signed-off-by:",
                "Suggested-by:",
                "Tested-by:",
                # Additional tags
                "(cherry picked from commit",
                "Change-Id",
                "Git-Commit:",
                "Git-repo",
                "Git-Repo:",
            }

            return any(text.startswith(tag) for tag in TAGS)

        def is_quote(text):
            return text.startswith(">")

        paragraphs = split_text_into_paragraphs(text)

        wrapped_paragraphs = [
            (
                textwrap.fill(
                    p,
                    width=75,
                    break_long_words=False,  # to preserve links
                )
                if not (is_commit_tag(p.strip()) or is_quote(p.strip()))
                else p
            )
            for p in paragraphs
        ]

        return "\n".join(wrapped_paragraphs)

    def setup(self):
        # The agent's host path base is the mounted root (which it navigates), not
        # the git subtree: under --kernel-tree the patch's tree is a subdirectory,
        # and the agent must still reach sibling projects (out-of-tree modules).
        # When there is no subtree, the mount root is the kernel tree (unchanged).
        self.agent = Agent(self.docker_manager.repo_path, self.docker_manager)

        self.diff = self.repo.git.diff(self.commit.parents[0], self.commit).strip()
        if not self.diff:
            self.logger.error("Failed to retrieve diff.")

        self.commit_message = self.repo.commit(self.commit).message.rstrip()
        if not self.commit_message:
            self.logger.error("Failed to retrieve commit message.")
