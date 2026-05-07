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
from git.objects.commit import Commit

from patchwise import PACKAGE_NAME, PACKAGE_PATH, SANDBOX_PATH
from patchwise.docker import DockerManager, CONTAINERS_BUILT

DOCKERFILES_PATH = PACKAGE_PATH / "dockerfiles"
BUILD_DIR = SANDBOX_PATH / "build"


class PatchReview(abc.ABC):
    @classmethod
    def get_logger(cls) -> logging.Logger:
        return logging.getLogger(f"{PACKAGE_NAME}.{cls.__name__.lower()}")

    def __init__(
        self,
        repo_path: str,
        commit: Commit,
        additional_context: str = "",
    ):
        self.logger = self.get_logger()
        self.repo = Repo(repo_path)
        self.commit = commit
        self.additional_context = additional_context
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
            repo_path=Path(repo_path),
            commit_sha=self.commit.hexsha,
        )

        # Build the image if not already built
        if container_name not in CONTAINERS_BUILT:
            self.docker_manager.build_image(dockerfile_path)
            CONTAINERS_BUILT[container_name] = self.docker_manager

        # Initialize shared build volume once using base container
        if not DockerManager.build_volume_initialized:
            DockerManager.initialize_shared_build_volume(
                Path(repo_path), self.commit.hexsha
            )
            DockerManager.build_volume_initialized = True

        # Start container with shared volume
        self.docker_manager.start_container_with_shared_volume()

        self.setup()

    def __del__(self):
        if self.docker_manager.container_name in CONTAINERS_BUILT:
            self.docker_manager.stop_container()
            del CONTAINERS_BUILT[self.docker_manager.container_name]

    def get_dockerfile_path(self):
        specific_dockerfile = DOCKERFILES_PATH / f"{self.__class__.__name__}.Dockerfile"
        if specific_dockerfile.exists():
            return specific_dockerfile
        return DOCKERFILES_PATH / "base.Dockerfile"

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
        stderr_only: bool = False,
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
                    if not stderr_only:
                        output += _stdout
                if _stderr:
                    self.logger.debug(_stderr)
                    output += _stderr

                if show_timer:
                    sys.stdout.write("\r\033[K")  # Clear to end of line
                    sys.stdout.flush()
                elapsed = int(time.time() - start)
                self.logger.debug(f"{desc}... {elapsed}s elapsed")
                break

            except subprocess.TimeoutExpired:
                elapsed = int(time.time() - start)
                if show_timer:
                    sys.stdout.write(f"\r\033[K{desc}... {elapsed}s elapsed")
                    sys.stdout.flush()
            except (Exception, KeyboardInterrupt) as e:
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
