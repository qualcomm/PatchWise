# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import argparse
import contextlib
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
from .patch_review.ai_review.root_cause_analysis import add_rca_arguments, run_rca_mode
from .patch_review import (
    _cleanup_all_containers,
    add_review_arguments,
    fix_reported_issues,
    get_selected_reviews_from_args,
    review_commit,
)
from patchwise.patch_review.ai_agent import add_ai_arguments, apply_ai_args
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
    parser.add_argument(
        "--rca",
        action="store_true",
        help="Root-cause a kernel crashdump folder instead of reviewing commits.",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Disable the live dashboard and use plain log output.",
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
        "--kernel-tree",
        default="",
        metavar="<path>",
        help=(
            "Kernel git subtree (has .git) when --repo-path is a broader workspace "
            "directory, e.g. --repo-path .../kernel_platform --kernel-tree common. "
            "Relative to --repo-path or absolute, and inside it. The agent navigates "
            "the whole --repo-path (so it can read out-of-tree modules) while git "
            "operations and the diff use this subtree. Defaults to --repo-path."
        ),
    )

    add_review_arguments(review_group)

    mail_group = parser.add_argument_group("Mail Options (require --mail)")
    add_mail_arguments(mail_group)

    rca_group = parser.add_argument_group("Crashdump RCA Options (require --rca)")
    add_rca_arguments(rca_group)

    ai_group = parser.add_argument_group("AI Review Options")
    add_ai_arguments(ai_group, config)

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
    used_rca_args = [
        action.option_strings[0]
        for action in rca_group._group_actions
        if getattr(args, action.dest) != action.default
    ]

    if args.mail and args.rca:
        parser.error("--mail and --rca are mutually exclusive")
    if not args.mail and used_mail_args:
        parser.error(f"{', '.join(used_mail_args)} may only be used with --mail")
    if args.mail and args.repo_path is not None:
        parser.error("--repo-path is not used in --mail mode")
    if not args.rca and used_rca_args:
        parser.error(f"{', '.join(used_rca_args)} may only be used with --rca")
    if (args.mail or args.rca) and args.commits is not None:
        mode = "--mail" if args.mail else "--rca"
        parser.error(f"--commits is not used in {mode} mode")
    if args.rca:
        if not args.dump:
            parser.error("--rca requires --dump <path>")

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

    # With --kernel-tree, --repo-path is a broader workspace and the commits live
    # in the kernel git subtree; resolve it so commit lookup uses the right repo.
    from patchwise.utils.repo_workspace import resolve_git_tree
    _, git_tree, _ = resolve_git_tree(args.repo_path, args.kernel_tree)
    repo = Repo(str(git_tree))
    commits = get_commits(repo, args.commits)

    for commit in commits:
        logger.info(f"Reviewing commit {commit.hexsha}...")

        results = review_commit(
            reviews,
            commit,
            args.repo_path,
            additional_context=args.additional_context,
            kernel_tree=args.kernel_tree,
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

    # The live dashboard only knows the event stream from AiCodeReview and the
    # crashdump RCA pipeline; checkpatch and the static-analysis reviews emit no
    # events and would run invisibly behind the footer (their INFO logs are
    # hidden). So the dashboard is limited to an --rca run or a local review
    # whose sole selected review is AiCodeReview — anything else falls back to
    # plain output. It also hides the INFO log stream, so it is suppressed when
    # debugging (--log-level DEBUG), when output is not a terminal
    # (piped/redirected), for --plain, and for the --mail daemon loop.
    ui_supported = args.rca or (
        not args.mail and get_selected_reviews_from_args(args) == {"AiCodeReview"}
    )
    use_ui = (
        ui_supported
        and sys.stdout.isatty()
        and not args.plain
        and args.log_level.upper() != "DEBUG"
    )
    if use_ui:
        from patchwise.ui.dashboard import live_dashboard
        dashboard_cm = live_dashboard(args)
    else:
        dashboard_cm = contextlib.nullcontext()

    with dashboard_cm as dashboard:
        try:
            if args.rca:
                run_rca_mode(args)
            elif args.mail:
                run_mail_mode(args)
            else:
                run_local_mode(args)
        except (KeyboardInterrupt, SystemExit):
            # First Ctrl-C lands here (the signal handler raises SystemExit).
            # begin_cleanup stops the live's refresh thread (so the static box
            # can't stack into scrollback during teardown) and shows 'cleaning
            # up…' in the box. Teardown commands run in their own process group,
            # so further Ctrl-C cannot interrupt them.
            if dashboard is not None:
                dashboard.begin_cleanup()
            _cleanup_all_containers()
            raise


if __name__ == "__main__":
    main()
