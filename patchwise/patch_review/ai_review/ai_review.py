# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import argparse
from getpass import getpass
import re
import textwrap
import os
import typing as t
import urllib3
import litellm, httpx
urllib3.disable_warnings()

from patchwise.patch_review.patch_review import PatchReview, Dependency

DEFAULT_MODEL = "Pro"
DEFAULT_API_BASE = "https://api.openai.com/v1"
API_KEY_NAME = "OPENAI_API_KEY"

def get_api_key(name: str = API_KEY_NAME) -> str:
    """
    Returns the environment variable value, caching it after the first retrieval.
    """
    if not hasattr(get_api_key, name):
        env_var = os.environ.get(name)
        if not env_var:
            try:
                env_var = getpass(f"Please enter your {name}: ").strip()
            except Exception:
                raise RuntimeError(f"{name} is not set and user input failed.")
            if not env_var:
                raise RuntimeError(f"{name} is required but was not provided.")
        setattr(get_api_key, name, env_var)
    return getattr(get_api_key, name)

class ModelProviderDependency(Dependency):
    def check(self) -> None:
        get_api_key(self.name)  # Ensure the API key is available

class AiReview(PatchReview):
    api_key: str
    model: str = DEFAULT_MODEL
    api_base: str = DEFAULT_API_BASE

    DEPENDENCIES = [ModelProviderDependency("OPENAI_API_KEY")]

    def format_chat_response(self, text: str) -> str:
        """
        Line wraps the given text at 75 columns but skips commit tags.
        """
        def split_text_into_paragraphs(text: str) -> list[str]:
            """
            Splits the input text into paragraphs, treating each bullet
            point line as a separate paragraph.
            """
            lines = text.split('\n')
            paragraphs = []
            current = []
            bullet_pattern = re.compile(r"""
                ^\s*                              # Optional leading whitespace
                (
                    [*+\->]                       # Unordered bullet characters
                    |                             # OR
                    \d+[.)-]                      # Numbered bullets like 1. or 2)
                    |                             # OR
                    \d+(\.\d+)+                   # Decimal bullets like 1.1 or 1.2.3
                )
                \s*                               # At least one space after the bullet
            """, re.VERBOSE)

            for line in lines:
                line_stripped = line.strip()
                if line_stripped == '' or line_stripped == '```' \
                        or line_stripped == '\'\'\'' or line_stripped == '\"\"\"' \
                        or bullet_pattern.match(line_stripped) != None:
                    if len(current) > 0:
                        paragraphs.append('\n'.join(current))
                        current = []
                    paragraphs.append(line)
                else:
                    current.append(line)
            if len(current) > 0:
                paragraphs.append('\n'.join(current))

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
            textwrap.fill(
                p,
                width=75,
                break_long_words=False,  # to preserve links
            ) if not (is_commit_tag(p.strip()) or is_quote(p.strip())) else p \
                for p in paragraphs
        ]

        return '\n'.join(wrapped_paragraphs)

    def provider_api_call(
        self,
        user_prompt: str,
        system_prompt: t.Optional[str] = None
    ) -> str:
        messages = [{"content": user_prompt, "role": "user"}]
        if system_prompt:
            messages.append({"content": system_prompt, "role": "system"})

        self.logger.debug(f"Making API call with model: {self.model}, api_base: {AiReview.api_base}")

        response = litellm.completion(
            model=self.model,
            api_base=AiReview.api_base,
            messages=messages,
            stream=False,
        )

        return response.choices[0].message.content

    def setup(self):
        self.model = AiReview.model

        os.environ["OTEL_SDK_DISABLED"] = "true"
        os.environ[API_KEY_NAME] = get_api_key(API_KEY_NAME)

        litellm.client_session = httpx.Client(verify=False)

        self.diff = self.repo.git.diff(self.base_commit, self.commit).strip()
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
        help="The AI model to use for review. (default: %(default)s)"
    )
    parser_or_group.add_argument(
        "--provider",
        default=DEFAULT_API_BASE,
        help="The base URL for the AI model API. (default: %(default)s)"
    )
    parser_or_group.add_argument(
        "--api-key",
        help=f"The API key for the AI model API. If not provided, it will be read from the environment variable `{API_KEY_NAME}`."
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
    if args.api_key:
        AiReview.api_key = args.api_key
