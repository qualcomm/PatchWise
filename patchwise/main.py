# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict

from git import Repo
from git.objects.commit import Commit
from rich_argparse import RichHelpFormatter

from patchwise import OUTPUT_PATH
from .logger_setup import add_logging_arguments, setup_logger
from .mail_handler.cli import add_mail_arguments, run_mail_mode
from .patch_review import (
    add_review_arguments,
    fix_reported_issues,
    get_selected_reviews_from_args,
    review_commit,
)
from patchwise.patch_review.ai_agent import add_ai_arguments, apply_ai_args
from .patch_review.ai_review.ai_code_review import (
    add_aicodereview_arguments,
    apply_aicodereview_args,
)
from .utils.config import parse_config, update_user_config
from .utils.tui import display_prompt_with_options

logger = logging.getLogger(__name__)


def parse_args(config: Dict) -> argparse.Namespace:
    parser = argparse.ArgumentParser(formatter_class=RichHelpFormatter)

    parser.add_argument(
        "--mail",
        action="store_true",
        help="Run the mail-handler loop instead of reviewing local commits.",
    )

    review_group = parser.add_argument_group("Patch Review Options")

    review_group.add_argument(
        "--commits",
        nargs="*",
        default=None,
        help="Space separated list of commit SHAs/refs, or a single commit range in start..end format. (default: HEAD)",
    )
    review_group.add_argument(
        "--repo-path",
        default=None,
        help="Path to the kernel workspace containing the patch(es) to review. Uses CWD if not specified. (default: CWD)",
    )
    review_group.add_argument(
        "--enable-experimental-features",
        action="store_true",
        help="Enable experimental features across all reviews.",
    )

    add_review_arguments(review_group)

    mail_group = parser.add_argument_group("Mail Options (require --mail)")
    add_mail_arguments(mail_group)

    ai_group = parser.add_argument_group("AI Review Options")
    add_ai_arguments(ai_group, config)

    aicodereview_group = parser.add_argument_group("AiCodeReview Options")
    add_aicodereview_arguments(aicodereview_group)

    logging_group = parser.add_argument_group("Logging Options")
    add_logging_arguments(logging_group, config)

    output_group = parser.add_argument_group("Output Options")
    output_group.add_argument(
        "--output-dir",
        default=str(OUTPUT_PATH),
        help="Directory to save the review results. (default: %(default)s)",
    )

    args = parser.parse_args()

    used_mail_args = [
        action.option_strings[0]
        for action in mail_group._group_actions
        if getattr(args, action.dest) != action.default
    ]

    if not args.mail and used_mail_args:
        parser.error(f"{', '.join(used_mail_args)} may only be used with --mail")
    if args.mail and args.commits is not None:
        parser.error("--commits is not used in --mail mode")
    if args.mail and args.repo_path is not None:
        parser.error("--repo-path is not used in --mail mode")

    if args.commits is None:
        args.commits = ["HEAD"]
    if args.repo_path is None:
        args.repo_path = str(Path.cwd())

    return args


def get_commits(repo: Repo, commits: list[str]) -> list[Commit]:
    """
    Given a repo and a list of commit refs or a commit range, return a list of Commit objects.
    - If commits is a list of refs (e.g., ["HEAD", "abc123"]) return those commits.
    - If commits is a single string in range format (e.g., "sha1..sha2"), return all commits in that range (inclusive of sha1, exclusive of sha2, like git log).
    """
    if isinstance(commits, str):
        commits = [commits]
    if len(commits) == 1 and ".." in commits[0]:
        # Range mode
        commit_range = commits[0]
        # Split the range into start and end
        start, end = commit_range.split("..", 1)
        # Get all commits reachable from start (inclusive) up to end (inclusive)
        # Use git rev-list --reverse start^..end to get chronological order
        inclusive_range = f"{start}^..{end}"
        commit_shas = list(repo.git.rev_list("--reverse", inclusive_range).splitlines())
        return [repo.commit(sha) for sha in commit_shas]
    else:
        # List of refs/SHAs
        return [repo.commit(ref) for ref in commits]


def run_local_mode(args: argparse.Namespace) -> None:
    reviews = get_selected_reviews_from_args(args)

    if (args.url is not None or args.cache_dir is not None) and not (
        args.enable_experimental_features and "AiCodeReview" in reviews
    ):
        passed = [
            flag
            for flag, val in (("--url", args.url), ("--cache-dir", args.cache_dir))
            if val is not None
        ]
        sys.exit(
            f"error: {' and '.join(passed)} only effective with --reviews aicodereview and --enable-experimental-features"
        )

    apply_aicodereview_args(args)

    repo = Repo(args.repo_path)
    commits = get_commits(repo, args.commits)

    for commit in commits:
        logger.info(f"Reviewing commit {commit.hexsha}...")

        results = review_commit(
            reviews,
            commit,
            args.repo_path,
            additional_context=args.additional_context,
            enable_experimental_features=args.enable_experimental_features,
        )

        fix_results = fix_reported_issues(results) if args.fix else {}

        output_dir = Path(args.output_dir) / commit.hexsha
        output_dir.mkdir(parents=True, exist_ok=True)
        for review, result_text in results.results.items():
            if not result_text:
                continue
            review_name = type(review).__name__
            output_file = output_dir / f"{review_name.lower()}.txt"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(result_text)
            logger.info(f"Saved {review_name} results to {output_file}")

        for fix_name, fix_text in fix_results.items():
            if not fix_text:
                continue
            output_file = output_dir / f"{fix_name.lower()}.patch"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(fix_text)
            logger.info(f"Saved {fix_name} results to {output_file}")


def main():
    config = parse_config()

    api_key_conf = config["api_key_disclaimer"]

    if not api_key_conf["no_reprompt"]:
        selected_option = display_prompt_with_options(
            api_key_conf["message"], api_key_conf["options"]
        )
        if selected_option == "Yes. Don't show again":
            api_key_conf["no_reprompt"] = True
            update_user_config(config)
        elif selected_option != "Yes":
            return

    args = parse_args(config)

    setup_logger(log_file=args.log_file, log_level=args.log_level)

    apply_ai_args(args)

    if args.mail:
        run_mail_mode(args)
    else:
        run_local_mode(args)


if __name__ == "__main__":
    main()
