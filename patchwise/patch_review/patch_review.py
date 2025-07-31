# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import abc
import inspect
import logging
import os
import re
import subprocess
import shutil
import sys
import time
from typing import Any, List, Union
from git import Repo
from git.exc import GitCommandError
from git.objects.commit import Commit
from packaging.version import Version, InvalidVersion
from patchwise import KERNEL_PATH, SANDBOX_BIN, SANDBOX_PATH, PACKAGE_NAME, PACKAGE_PATH
from .kernel_tree import BRANCH_NAME

PATCH_PATH = PACKAGE_PATH / "patches"
BUILD_DIR = SANDBOX_PATH / "build"


class Dependency:
    def __init__(
        self,
        name: str,
        min_version: Union[int, float, str, None] = None,
        max_version: Union[int, float, str, None] = None,
    ):
        self.name = name
        self.logger = logging.getLogger(
            f"{PACKAGE_NAME}.{__name__.lower()}.{self.name}"
        )
        self.min_version: Version | None = None
        self.max_version: Version | None = None
        if min_version is not None:
            self.min_version = Version(str(min_version))
        if max_version is not None:
            self.max_version = Version(str(max_version))

    def version_in_range(self, version: Version) -> bool:
        if (self.min_version is not None and version < self.min_version) or (self.max_version is not None and version > self.max_version):
            return False
        return True

    def get_version(self) -> Version:
        out = subprocess.check_output([self.name, "--version"], text=True)
        match = re.search(r"(\d+\.\d+\.\d+)", out)
        version = Version(match.group(1))

        return version

    def check(self) -> None:
        cmd_path = shutil.which(self.name)
        if cmd_path is None or not os.access(cmd_path, os.X_OK):
            raise ImportError(
                f"{self.name} is not installed or not executable. Please install {self.name}."
            )
        self.logger.debug(f"{self.name} is installed and executable at {cmd_path}.")

        if self.min_version is None and self.max_version is None:
            return

        minmax: list[str] = []
        if self.min_version:
            minmax.append(f">= {self.min_version}")
        if self.max_version:
            minmax.append(f"<= {self.max_version}")
        minmax_str = ", ".join(minmax)

        try:
            version = self.get_version()
            if not self.version_in_range(version):
                raise ImportError(
                    f"{self.name} version {{{version}}} does not meet the version requirements ({minmax_str})."
                )
            self.logger.debug(
                f"{self.name} version {{{version}}} is installed and meets the version requirements ({minmax_str})."
            )
        except (FileNotFoundError, subprocess.CalledProcessError, InvalidVersion):
            raise ImportError(
                f"{self.name} is not installed or not working. Please install {self.name} ({minmax_str})."
            )

    def install_from_pkg_manager(self) -> None:
        pkg_managers: list[tuple[str, list[str] | None, list[str]]] = [
            ("apt-get", ["sudo", "apt-get", "update"], ["sudo", "apt-get", "install", "-y", self.name]),
            ("dnf", None, ["sudo", "dnf", "install", "-y", self.name]),
            ("yum", None, ["sudo", "yum", "install", "-y", self.name]),
            ("zypper", None, ["sudo", "zypper", "install", "-y", self.name]),
            ("pacman", None, ["sudo", "pacman", "-Sy", self.name]),
        ]
        for mgr, pre, install_cmd in pkg_managers:
            if shutil.which(mgr):
                try:
                    if pre:
                        subprocess.run(pre, check=True)
                    subprocess.run(install_cmd, check=True)
                    break
                except Exception:
                    continue

    def _do_install(self) -> None:
        """
        Subclasses must implement this method to install the dependency.
        """
        method_name = (
            f"{self.__class__.__name__}.{inspect.currentframe().f_code.co_name}"
        )
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement {method_name}."
        )

    def install(self) -> None:
        try:
            self.check()
        except ImportError as e:
            self.logger.warning(f"{e}")
            self.logger.info("Preparing to install...")
            self._do_install()
            self.check()


class PatchReview(abc.ABC):

    # Subclasses must define a list of Dependency objects
    DEPENDENCIES: list[Dependency]

    @classmethod
    def get_logger(cls) -> logging.Logger:
        return logging.getLogger(f"{PACKAGE_NAME}.{cls.__name__.lower()}")

    def __init__(self, commit: Commit, base_commit: Commit | None = None):
        self.logger = self.get_logger()
        self.__class__.verify_dependencies()
        self.repo = Repo(KERNEL_PATH)
        self.commit = commit
        # The default for base_commit is the parent of the commit if not provided
        # TODO alternatively use FETCH_HEAD after a git fetch
        self.base_commit = base_commit or commit.parents[0]
        self.build_dir = BUILD_DIR / str(self.commit.hexsha)
        self.build_dir.mkdir(parents=True, exist_ok=True)
        self.apply_patches([self.commit])
        self.rebase_commit = self.repo.head.commit
        self.setup()

    _sandbox_path_added = False

    @staticmethod
    def add_sandbox_to_path():
        """
        Adds the sandbox bin directory to the PATH environment variable if not already present.
        """
        if not PatchReview._sandbox_path_added:
            current_path = os.environ.get("PATH", "")
            if SANDBOX_BIN not in current_path.split(":"):
                os.environ["PATH"] = str(SANDBOX_BIN) + ":" + current_path
                PatchReview.get_logger().debug(f"Added {SANDBOX_BIN} to PATH.")
            else:
                PatchReview.get_logger().debug(f"{SANDBOX_BIN} already in PATH.")
            PatchReview._sandbox_path_added = True
        else:
            PatchReview.get_logger().debug("Sandbox path already added to PATH.")

    @classmethod
    def verify_dependencies(cls, install: bool = False) -> None:
        """
        Verifies that all dependencies are installed and meet the minimum version requirements.
        """
        cls.add_sandbox_to_path()

        if not getattr(cls, "_dependencies_verified", False):
            for dependency in cls.DEPENDENCIES:
                if install:
                    dependency.install()
                else:
                    dependency.check()
            cls.get_logger().debug(f"{cls.__name__} dependencies are installed.")
            setattr(cls, "_dependencies_verified", True)

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

    def apply_patches(self, commits: list[Commit]) -> None:
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

        cherry_commits = commits or [self.commit]
        for cherry_commit in cherry_commits:
            self.logger.debug(f"Applying commit: {cherry_commit.hexsha}")
            try:
                self.repo.git.cherry_pick(cherry_commit.hexsha)
            except Exception as e:
                # If the commit is already applied or cherry-pick fails, log and continue
                self.logger.warning(
                    f"Failed to cherry-pick {cherry_commit.hexsha}: {e}"
                )

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
        cwd: str,
        stdout: int | None = subprocess.PIPE,
        stderr: int | None = subprocess.PIPE,
        **kwargs: Any,
    ) -> str:
        """
        Runs a make command and displays a timer while it runs,
        but only if logger level is INFO or lower.

        Parameters:
            cmd (str): The command to run using subprocess.Popen().
            desc (str): The title for the timer
            stdout_path (str, optional): Path to file for stdout. Defaults to None.
            stderr_path (str, optional): Path to file for stderr. Defaults to None.
            **kwargs: Rest of the args for subprocess.Popen.

        Returns:
            str: Output of running the command (stdout + stderr).
                 To skip stdout/stderr, pass stdout/stderr=subprocess.DEVNULL.
        """
        show_timer = self.logger.isEnabledFor(logging.INFO)
        start = time.time()

        with subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=stdout,
            stderr=stderr,
            text=True,
            bufsize=1,
            universal_newlines=True,
            **kwargs,
        ) as process:
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

            return output  # TODO return a tuple of (stdout, stderr) if both are needed

    @abc.abstractmethod
    def run(self) -> str:
        """
        Execute the patch review.

        This method must be overridden by subclasses. It should contain the logic
        for the specific type of patch review being performed.
        """
        pass
