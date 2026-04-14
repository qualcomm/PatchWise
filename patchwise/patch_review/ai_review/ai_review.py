# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import argparse
import json
import os
import re
import textwrap
import typing as t

import httpx
import litellm
import urllib3

urllib3.disable_warnings()

from patchwise.patch_review.patch_review import PatchReview
from patchwise.utils.decorators import retry

DEFAULT_MODEL = "Pro"
DEFAULT_API_BASE = "https://api.openai.com/v1"
AGENT_MAX_ITERATIONS = 25


class AiReview(PatchReview):
    model: str = DEFAULT_MODEL
    api_base: str = DEFAULT_API_BASE

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

    @retry(
        max_retries=10,
        exceptions=(
            litellm.Timeout,
            litellm.RateLimitError,
            litellm.InternalServerError,
            litellm.OpenAIError,
        ),
    )
    def _completion_with_retry(self, **kwargs) -> t.Any:
        self.logger.debug(
            f"Making API call with model: {self.model}, api_base: {AiReview.api_base}"
        )
        return litellm.completion(**kwargs)

    def dispatch_tool(self, name: str, args: dict) -> dict:
        """Dispatch a tool call by name. Subclasses override to register tools."""
        return {"ok": False, "error": f"unknown tool: {name}"}

    def get_tools(self) -> t.Optional[list[dict]]:
        """Return a list of tool definitions (LiteLLM/OpenAI format). Subclasses override."""
        return None

    def run_agent_loop(self, messages: list[dict]) -> str:
        """Run the agent loop, calling the LLM iteratively until it stops requesting tools.

        Args:
            messages: Initial message list (system + user turns).

        Returns:
            The final assistant text response.
        """
        tools = self.get_tools()

        completion_kwargs: dict = {
            "model": self.model,
            "api_base": AiReview.api_base,
            "messages": messages,
            "stream": False,
        }

        if tools:
            if not litellm.supports_function_calling(model=self.model):
                self.logger.warning(
                    f"Model '{self.model}' does not support function calling according to litellm. "
                    "Running without tools."
                )
            else:
                completion_kwargs["tools"] = tools
                completion_kwargs["tool_choice"] = "auto"

        for iteration in range(1, AGENT_MAX_ITERATIONS + 1):
            self.logger.debug(f"Agent iteration {iteration}/{AGENT_MAX_ITERATIONS}")

            response = self._completion_with_retry(**completion_kwargs)
            msg = response.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))

            if not msg.tool_calls:
                return msg.content or ""

            # Dispatch each tool call and append results
            for tool_call in msg.tool_calls:
                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                    self.logger.debug(f"Tool call: {name}({args})")
                    result = self.dispatch_tool(name, args)
                    self.logger.debug(f"Tool result: {name} -> {result}")
                except json.JSONDecodeError as e:
                    self.logger.error(f"Error parsing tool args for '{name}': {e}")
                    result = {"ok": False, "error": f"Invalid JSON arguments `{args}` for tool '{name}'"}
                except Exception as e:
                    self.logger.error(f"Error executing tool '{name}': {e}")
                    result = {"ok": False, "error": f"Internal error executing tool '{name}({args})'"}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": name,
                    "content": json.dumps(result),
                })

            completion_kwargs["messages"] = messages

        # Max iterations reached — force a final response without tools
        self.logger.warning(
            f"Agent reached max iterations ({AGENT_MAX_ITERATIONS}). Forcing final response without tools."
        )

        completion_kwargs.pop("tools", None)
        completion_kwargs.pop("tool_choice", None)

        messages.append({
            "role": "system",
            "content": "Maximum tool iterations reached. Please provide your final response based on the available information."
        })
        completion_kwargs["messages"] = messages

        response = self._completion_with_retry(**completion_kwargs)
        return response.choices[0].message.content or ""

    def setup(self):
        self.model = AiReview.model

        os.environ["OTEL_SDK_DISABLED"] = "true"

        litellm.client_session = httpx.Client(verify=False)

        self.diff = self.repo.git.diff(self.commit.parents[0], self.commit).strip()
        if not self.diff:
            self.logger.error("Failed to retrieve diff.")

        self.commit_message = self.repo.commit(self.commit).message.rstrip()
        if not self.commit_message:
            self.logger.error("Failed to retrieve commit message.")


def add_ai_arguments(
    parser_or_group: argparse.ArgumentParser | argparse._ArgumentGroup,
):
    parser_or_group.add_argument(
        "--model",
        default=f"openai/{AiReview.model}",
        help="The AI model to use for review. (default: %(default)s)",
    )
    parser_or_group.add_argument(
        "--provider",
        default=DEFAULT_API_BASE,
        help="The base URL for the AI model API. (default: %(default)s)",
    )
    # parser_or_group.add_argument(
    #     "--review-threshold",
    #     type=float,
    #     default=0.5,
    #     help="The threshold for review confidence. (default: %(default)s)"
    # )


def apply_ai_args(args: argparse.Namespace) -> None:
    """
    Applies AI-related arguments to the AiReview class.
    This function is called after parsing command line arguments.
    """
    AiReview.model = args.model
    AiReview.api_base = args.provider
