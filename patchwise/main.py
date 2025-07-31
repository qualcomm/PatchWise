# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import argparse
import logging
from pathlib import Path
from git import Repo
from git.objects.commit import Commit
from rich_argparse import RichHelpFormatter

from .logger_setup import setup_logger, add_logging_arguments
from .patch_review.kernel_tree import create_git_worktree
from .patch_review.patch_review import PATCH_PATH
from .patch_review import (
    review_patch,
    add_review_arguments,
    get_selected_reviews_from_args,
    install_missing_dependencies,
)
from .patch_review.ai_review.ai_review import add_ai_arguments, apply_ai_args


logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(formatter_class=RichHelpFormatter)

    review_group = parser.add_argument_group("Patch Review Options")

    review_group.add_argument(
        "--commits",
        nargs="*",
        default=["HEAD"],
        help="Space separated list of commit SHAs/refs, or a single commit range in start..end format. (default: %(default)s)",
    )
    review_group.add_argument(
        "--repo-path",
        default=str(Path.cwd()),
        help="Path to the kernel workspace containing the patch(es) to review. Uses CWD if not specified. (default: %(default)s)",
    )

    add_review_arguments(review_group)

    ai_group = parser.add_argument_group("AI Review Options")
    add_ai_arguments(ai_group)

    logging_group = parser.add_argument_group("Logging Options")
    add_logging_arguments(logging_group)

    return parser.parse_args()


def get_patches(repo: Repo, commits: list[Commit]):
    dest_dir = PATCH_PATH / "user"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for idx, commit in enumerate(commits, 1):
        patch_file = dest_dir / f"{idx:04d}-{commit}.patch"
        diff = repo.git.format_patch(f"-1", commit, stdout=True)
        logger.debug(f"Writing patch for commit {commit} to {patch_file}")
        patch_file.write_text(diff)


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
        # git rev-list returns commits in reverse chronological order
        commit_shas = list(repo.git.rev_list(commit_range).splitlines())
        return [repo.commit(sha) for sha in commit_shas]
    else:
        # List of refs/SHAs
        return [repo.commit(ref) for ref in commits]


def main():
    args = parse_args()

    setup_logger(log_file=args.log_file, log_level=args.log_level)

    apply_ai_args(args)

    reviews = get_selected_reviews_from_args(args)

    if args.install:
        install_missing_dependencies(reviews)
        return

    repo = Repo(args.repo_path)
    commits = get_commits(repo, args.commits)
    create_git_worktree(repo)

    for commit in commits:
        logger.info(f"Reviewing commit {commit.hexsha}...")
        review_patch(reviews, commit)


if __name__ == "__main__":
    main()
