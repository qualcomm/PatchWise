# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import logging
from typing import Any, Optional

from git import GitCommandError, RemoteProgress, Repo
from tqdm import tqdm

from patchwise import PACKAGE_NAME

logger = logging.getLogger(__name__)


BRANCH_NAME = f"{PACKAGE_NAME}-linux-next-stable"


class TqdmFetchProgress(RemoteProgress):
    def __init__(self):
        super().__init__()
        self.pbar: "Optional[tqdm[Any]]" = None

    def update(
        self,
        op_code: int,
        cur_count: str | float,
        max_count: str | float | None = None,
        message: str = "",
    ):
        if max_count is not None:
            max_count_float = float(max_count)
            cur_count_float = float(cur_count)
            if self.pbar is None:
                self.pbar = tqdm(
                    total=max_count_float,
                    unit="obj",
                    desc="Fetching",
                    leave=True,
                    colour="green",
                )
            self.pbar.n = cur_count_float
            self.pbar.refresh()
            if cur_count_float >= max_count_float:
                self.pbar.close()
                self.pbar = None
        elif self.pbar is None:
            self.pbar = tqdm(unit="obj", desc="Fetching", leave=True, colour="green")
            self.pbar.n = float(cur_count)
            self.pbar.refresh()


def fetch_and_branch(repo: Repo) -> None:
    git_url = "git://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"
    http_url = "https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"

    if PACKAGE_NAME not in [remote.name for remote in repo.remotes]:
        repo.create_remote(PACKAGE_NAME, git_url)
    try:
        repo.remotes[PACKAGE_NAME].set_url(git_url)
        repo.remotes[PACKAGE_NAME].fetch("stable", progress=TqdmFetchProgress())
    except GitCommandError:
        logger.warning("git: Failed, trying https:")
        repo.remotes[PACKAGE_NAME].set_url(http_url)
        try:
            repo.remotes[PACKAGE_NAME].fetch("stable", progress=TqdmFetchProgress())
        except GitCommandError:
            logger.error("https: Failed, exiting...")
            raise

    # Force-create the branch at FETCH_HEAD, do not check it out
    repo.git.branch("-f", BRANCH_NAME, "FETCH_HEAD")
