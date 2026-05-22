# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import argparse

from .agent import Agent


def add_ai_arguments(
    parser_or_group: argparse.ArgumentParser | argparse._ArgumentGroup,
):
    parser_or_group.add_argument(
        "--model",
        default=f"openai/{Agent.model}",
        help="The AI model to use for review. (default: %(default)s)",
    )
    parser_or_group.add_argument(
        "--provider",
        default=Agent.api_base,
        help="The base URL for the AI model API. (default: %(default)s)",
    )
    parser_or_group.add_argument(
        "--additional-context",
        default="",
        help="Extra text injected into the AI Code Review prompt.",
    )


def apply_ai_args(args: argparse.Namespace) -> None:
    """
    Applies AI-related arguments to the AiReview class.
    This function is called after parsing command line arguments.
    """
    Agent.model = args.model
    Agent.api_base = args.provider
