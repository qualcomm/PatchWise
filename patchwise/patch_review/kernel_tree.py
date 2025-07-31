# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from git import Repo, RemoteProgress, GitCommandError
from pathlib import Path
import logging
import shutil
from tqdm import tqdm
from patchwise import KERNEL_PATH, PACKAGE_NAME

logger = logging.getLogger(__name__)


BRANCH_NAME = f"{PACKAGE_NAME}-linux-next-stable"


class TqdmFetchProgress(RemoteProgress):
    def __init__(self):
        super().__init__()
        self.pbar = None

    def update(self, op_code, cur_count, max_count=None, message=""):
        if max_count:
            if self.pbar is None:
                self.pbar = tqdm(
                    total=max_count,
                    unit="obj",
                    desc="Fetching",
                    leave=True,
                    colour="green",
                )
            self.pbar.n = cur_count
            self.pbar.refresh()
            if cur_count >= max_count:
                self.pbar.close()
                self.pbar = None
            else:
                pass
        elif self.pbar is None:
            self.pbar = tqdm(
                unit="obj",
                desc="Fetching",
                leave=True,
                colour="green",
            )
            self.pbar.n = cur_count
            self.pbar.refresh()
        else:
            pass


def fetch_and_branch(repo: Repo) -> None:
    git_url = "git://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"
    http_url = "https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"

    if PACKAGE_NAME not in [remote.name for remote in repo.remotes]:
        repo.create_remote(PACKAGE_NAME, git_url)
    try:
        repo.remotes[PACKAGE_NAME].set_url(git_url)
        repo.remotes[PACKAGE_NAME].fetch("stable", progress=TqdmFetchProgress())
    except GitCommandError as git_error:
        logger.warning("git: Failed, trying https:")
        repo.remotes[PACKAGE_NAME].set_url(http_url)
        try:
            repo.remotes[PACKAGE_NAME].fetch("stable", progress=TqdmFetchProgress())
        except GitCommandError as http_error:
            logger.error("https: Failed, exiting...")
            raise

    # Force-create the branch at FETCH_HEAD, do not check it out
    repo.git.branch("-f", BRANCH_NAME, "FETCH_HEAD")


def init_kernel_tree(path: Path = KERNEL_PATH) -> Repo:

    path.mkdir(parents=True, exist_ok=True)

    repo = Repo.init(path)

    fetch_and_branch(repo)

    return repo


def create_git_worktree(
    repo: Repo, branch_name: str = BRANCH_NAME, worktree_path: Path = KERNEL_PATH
):
    """
    Create a new git worktree at worktree_path from repo_path using branch_name.
    If the worktree already exists at worktree_path, do nothing (reentrant).
    """
    # Prune worktrees first
    try:
        repo.git.worktree("prune")
    except GitCommandError as e:
        logger.warning(f"Could not prune worktrees: {e}")

    fetch_and_branch(repo)

    # Check if the path exists and if it's a worktree
    if worktree_path.exists():
        is_worktree = False
        try:
            worktrees = repo.git.worktree("list", "--porcelain").split("\n")
            for line in worktrees:
                if line.startswith("worktree "):
                    wt_path = line.split(" ", 1)[1].strip()
                    if Path(wt_path).resolve() == worktree_path.resolve():
                        is_worktree = True
                        break
        except GitCommandError as e:
            logger.warning(f"Could not list worktrees: {e}")

        if is_worktree:
            logger.info(f"Worktree already exists at {worktree_path}")
            return
        else:
            logger.info(
                f"Directory {worktree_path} exists but is not a worktree, removing it."
            )
            shutil.rmtree(worktree_path)

    # Create the worktree
    try:
        repo.git.worktree("add", str(worktree_path), branch_name)
        logger.info(f"Created worktree at {worktree_path} for branch {branch_name}")
    except GitCommandError as e:
        logger.error(f"Failed to create worktree: {e}")
        raise
