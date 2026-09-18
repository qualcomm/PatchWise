# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from pathlib import Path
import re
import textwrap

from pygments.lexers import CLexer
from pygments.token import Token

from patchwise.patch_review.ai_agent.agent import Agent
from patchwise.patch_review.patch_review import PatchReview


class AiReview(PatchReview):

    CODE_TOKEN_RATIO = 0.5

    @staticmethod
    def _is_c_code(text: str) -> bool:
        """
        Heuristic: does this paragraph look like C rather than prose about C?
        Unreliable on short fragments, so callers gate it on multi-line text.
        """
        tokens = [
            token for token, value in CLexer().get_tokens(text) if value.strip()
        ]
        if not tokens:
            return False
        code_tokens = sum(
            1
            for token in tokens
            if token in Token.Keyword
            or token in Token.Keyword.Type
            or token in Token.Operator
            or token in Token.Punctuation
            or token in Token.Comment
            or token in Token.Literal.Number
        )
        return code_tokens / len(tokens) > AiReview.CODE_TOKEN_RATIO

    def format_chat_response(self, text: str) -> str:
        """
        Line wraps the given text at 75 columns but skips commit tags, quoted
        text, and the AI's own code. A paragraph whose lines already respect the
        limit is emitted verbatim.
        """

        def split_into_code_blocks(text: str) -> list[tuple[bool, str]]:
            """
            Splits the text into (is_code, block) pairs on ``` fences.
            An unclosed fence keeps the remainder verbatim.
            """
            blocks: list[tuple[bool, str]] = []
            current: list[str] = []
            in_code = False

            for line in text.split("\n"):
                is_fence = line.strip().startswith("```")
                if is_fence and not in_code and len(current) > 0:
                    blocks.append((False, "\n".join(current)))
                    current = []
                current.append(line)
                if is_fence:
                    if in_code:
                        blocks.append((True, "\n".join(current)))
                        current = []
                    in_code = not in_code
            if len(current) > 0:
                blocks.append((in_code, "\n".join(current)))

            return blocks

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
                \s*                               # At least one* space after the bullet
            """,
                re.VERBOSE,
            )                                     # * - to cover **Commit Analysis** as a bullet

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

        def is_tabbed(text: str) -> bool:
            return any(line.startswith(("\t", " ")) for line in text.split("\n"))

        def fits(text: str) -> bool:
            return all(len(line) <= 75 for line in text.split("\n"))

        def wrap_paragraph(p: str) -> str:
            stripped = p.strip()
            if (
                not stripped
                or fits(p)  # Benefit of doubt to the review-cleanup agent
                or is_commit_tag(stripped)
                or is_quote(stripped)
                or is_tabbed(p)
            ):
                return p
            if "\n" in stripped and self._is_c_code(p):
                return p
            return textwrap.fill(
                p,
                width=75,
                break_long_words=False,  # to preserve links
            )

        wrapped_blocks = [
            (
                block
                if is_code
                else "\n".join(
                    wrap_paragraph(p) for p in split_text_into_paragraphs(block)
                )
            )
            for is_code, block in split_into_code_blocks(text)
        ]

        return "\n".join(wrapped_blocks)

    def setup(self):
        # The agent navigates the whole mounted --repo-path (so it can reach sibling
        # projects), not just the commit's subtree.
        self.agent = Agent(self.docker_manager.repo_path, self.docker_manager)

        self.diff = self.repo.git.diff(self.commit.parents[0], self.commit).strip()
        if not self.diff:
            self.logger.error("Failed to retrieve diff.")

        self.commit_message = self.repo.commit(self.commit).message.rstrip()
        if not self.commit_message:
            self.logger.error("Failed to retrieve commit message.")
