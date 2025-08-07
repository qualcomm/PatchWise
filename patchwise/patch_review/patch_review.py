# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import abc
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, List, Optional

from git import Repo
from git.exc import GitCommandError
from git.objects.commit import Commit

from patchwise import PACKAGE_NAME, PACKAGE_PATH, SANDBOX_PATH
from patchwise.docker import DockerManager

from .kernel_tree import BRANCH_NAME

DOCKERFILES_PATH = PACKAGE_PATH / "dockerfiles"
PATCH_PATH = PACKAGE_PATH / "patches"
BUILD_DIR = SANDBOX_PATH / "build"


class PatchReview(abc.ABC):
    @classmethod
    def get_logger(cls) -> logging.Logger:
        return logging.getLogger(f"{PACKAGE_NAME}.{cls.__name__.lower()}")

    def __init__(
        self,
        repo_path: str,
        commit: Commit,
        base_commit: Commit | None = None,
    ):
        self.logger = self.get_logger()
        self.repo = Repo(repo_path)
        self.commit = commit
        # The default for base_commit is the parent of the commit if not provided
        # TODO alternatively use FETCH_HEAD after a git fetch
        self.base_commit = base_commit or commit.parents[0]
        self.build_dir = BUILD_DIR / str(self.commit.hexsha)
        self.build_dir.mkdir(parents=True, exist_ok=True)

        dockerfile_path = self.get_dockerfile_path()
        if dockerfile_path.name == "base.Dockerfile":
            image_tag = "patchwise-base:latest"
        else:
            image_tag = f"{PACKAGE_NAME.lower()}-{self.__class__.__name__.lower()}"
        container_name = f"{image_tag.replace(':', '-')}-{self.commit.hexsha}"

        self.docker_manager = DockerManager(
            image_tag=image_tag,
            container_name=container_name,
        )
        self.docker_manager.build_image(dockerfile_path, Path(repo_path))
        self.docker_manager.start_container(self.build_dir)

        self.apply_patches([self.commit])
        self.rebase_commit = self.repo.head.commit
        self.setup()

    def __del__(self):
        self.docker_manager.stop_container()

    def get_dockerfile_path(self):
        specific_dockerfile = DOCKERFILES_PATH / f"{self.__class__.__name__}.Dockerfile"
        if specific_dockerfile.exists():
            return specific_dockerfile
        return DOCKERFILES_PATH / "base.Dockerfile"

    def git_abort(self) -> None:
        """
        Abort any ongoing git operations.
        """
        self.logger.debug("Attempting to abort any ongoing git operations.")
        try:
            self.repo.git.am("--abort")
        except GitCommandError:
            pass
        try:
            self.repo.git.rebase("--abort")
        except GitCommandError:
            pass
        try:
            self.repo.git.cherry_pick("--abort")
        except GitCommandError:
            pass
        try:
            self.repo.git.merge("--abort")
        except GitCommandError:
            pass

    def apply_patches(self, commits: list[Commit]) -> Commit:
        self.git_abort()
        self.repo.git.switch(BRANCH_NAME, detach=True)
        self.logger.debug(f"Applying patches from {PATCH_PATH} on branch {BRANCH_NAME}")
        general_patch_files = sorted((PATCH_PATH / "general").glob("*.patch"))
        self.logger.debug(f"Applying general patches: {general_patch_files}")
        review_patch_files = sorted(
            (PATCH_PATH / self.__class__.__name__.lower()).glob("*.patch")
        )
        self.logger.debug(f"Applying review patches: {review_patch_files}")
        patch_files = general_patch_files + review_patch_files
        for patch_file in patch_files:
            self.logger.debug(f"Applying patch: {patch_file}")
            try:
                self.repo.git.am(str(patch_file))
            except Exception as e:
                self.logger.warning(f"Failed to apply patch {patch_file}: {e}")
                self.repo.git.am("--skip")

        cherry_commits = commits
        for cherry_commit in cherry_commits:
            self.logger.debug(f"Applying commit: {cherry_commit.hexsha}")
            try:
                self.repo.git.cherry_pick(cherry_commit.hexsha)
            except Exception as e:
                # If the commit is already applied or cherry-pick fails, log and continue
                self.logger.warning(
                    f"Failed to cherry-pick {cherry_commit.hexsha}: {e}"
                )
        return self.repo.head.commit

    @abc.abstractmethod
    def setup(self) -> None:
        """
        Set up the environment for the patch review.
        """
        pass

    def run_cmd_with_timer(
        self,
        cmd: List[str],
        desc: str,
        cwd: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Runs a make command and displays a timer while it runs,
        but only if logger level is INFO or lower.

        Parameters:
            cmd (str): The command to run using subprocess.Popen().
            desc (str): The title for the timer
            cwd (str, optional): The working directory for the command. Defaults to None.
            **kwargs: Rest of the args for subprocess.Popen.

        Returns:
            str: Output of running the command (stdout + stderr).
        """
        show_timer = self.logger.isEnabledFor(logging.INFO)
        start = time.time()

        process = self.docker_manager.run_command(cmd, cwd=cwd, **kwargs)

        output = ""
        while True:
            try:
                _stdout, _stderr = process.communicate(timeout=5)
                if _stdout:
                    self.logger.debug(_stdout)
                    output += _stdout
                if _stderr:
                    self.logger.debug(_stderr)
                    output += _stderr

                if show_timer:
                    sys.stdout.write("\r" + " " * 40 + "\r")  # Clear the line
                    sys.stdout.flush()
                elapsed = int(time.time() - start)
                self.logger.debug(f"{desc}... {elapsed}s elapsed")
                break

            except subprocess.TimeoutExpired:
                elapsed = int(time.time() - start)
                if show_timer:
                    sys.stdout.write(f"\r{desc}... {elapsed}s elapsed")
                    sys.stdout.flush()

            except Exception:
                process.kill()
                raise

        return output

    @abc.abstractmethod
    def run(self) -> str:
        """
        Execute the patch review.

        This method must be overridden by subclasses. It should contain the logic
        for the specific type of patch review being performed.
        """
        pass
