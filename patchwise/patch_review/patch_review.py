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
from patchwise.utils.repo_workspace import resolve_git_tree

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
        kernel_tree: str = "",
    ):
        self.logger = self.get_logger()
        # The container mounts `repo_path` (what the agent navigates); the git tree
        # holding the patch is `kernel_tree` — a subdirectory of it when reviewing
        # inside a broader workspace, or the mount root itself when unset. `self.repo`
        # is the git tree (diff/commit), `self.git_subdir` its path within the mount.
        mount_root, git_tree, self.git_subdir = resolve_git_tree(repo_path, kernel_tree)
        self.repo = Repo(str(git_tree))
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
            repo_path=mount_root,
            commit_sha=self.commit.hexsha,
            git_subdir=self.git_subdir,
        )

        # Build the image if not already built
        if container_name not in CONTAINERS_BUILT:
            self.docker_manager.build_image(dockerfile_path)
            CONTAINERS_BUILT[container_name] = self.docker_manager

        # Initialize shared build volume once using base container
        if not DockerManager.build_volume_initialized:
            DockerManager.initialize_shared_build_volume(
                mount_root, self.commit.hexsha
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

    @abc.abstractmethod
    def run(self) -> str:
        """
        Execute the patch review.

        This method must be overridden by subclasses. It should contain the logic
        for the specific type of patch review being performed.
        """
        pass
