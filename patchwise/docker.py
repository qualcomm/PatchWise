# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Optional

from patchwise import PACKAGE_NAME, PACKAGE_PATH


class DockerManager:
    def __init__(self, image_tag: str, container_name: str):
        self.logger = logging.getLogger(
            f"{PACKAGE_NAME}.{self.__class__.__name__.lower()}"
        )
        self.image_tag = image_tag
        self.container_name = container_name
        self.sandbox_path = Path("/home") / PACKAGE_NAME
        self.build_dir = self.sandbox_path / "build"
        self.kernel_dir = self.sandbox_path / "kernel"

    def _stream_build_output(self, process: subprocess.Popen[str]) -> None:
        if process.stdout:
            for line in iter(process.stdout.readline, b""):
                self.logger.info(line.strip())
        if process.stderr:
            for line in iter(process.stderr.readline, ""):
                self.logger.error(line.strip())
        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, process.args)

    def build_image(
        self, dockerfile_path: Path, repo_path: Path, current_commit_sha: str
    ) -> None:
        base_image_tag = "patchwise-base:latest"
        self.logger.info(f"Ensuring base Docker image {base_image_tag} is built...")
        base_dockerfile = PACKAGE_PATH / "dockerfiles" / "base.Dockerfile"

        # Find the common ancestor path for the build context
        common_path = Path(os.path.commonpath([PACKAGE_PATH, repo_path]))
        self.logger.debug(f"Using common path for build context: {common_path}")

        # Calculate relative paths for the build context
        relative_package_path = PACKAGE_PATH.relative_to(common_path)
        relative_repo_path = repo_path.relative_to(common_path)
        self.logger.debug(f"Relative package path: {relative_package_path}")
        self.logger.debug(f"Relative repo path: {relative_repo_path}")

        process = subprocess.Popen(
            [
                "docker",
                "build",
                "-f",
                str(base_dockerfile),
                "--build-arg",
                f"PACKAGE_PATH={relative_package_path}",
                "--build-arg",
                f"KERNEL_PATH={relative_repo_path}",
                "--build-arg",
                f"CURRENT_COMMIT_SHA={current_commit_sha}",
                "-t",
                base_image_tag,
                str(common_path),
            ],
            text=True,
        )
        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, process.args)
        self.logger.info(f"Base Docker image {base_image_tag} built successfully.")

        if self.image_tag != base_image_tag:
            docker_build_args = [
                "docker",
                "build",
                "-f",
                str(dockerfile_path),
                "-t",
                self.image_tag,
                str(PACKAGE_PATH),
            ]
                
            self.logger.info(
                f"Building Docker image {self.image_tag} with args {' '.join(docker_build_args)} ..."
            )
            process = subprocess.Popen(
                docker_build_args,
                text=True,
            )
            process.wait()
            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, process.args)
            self.logger.info(f"Docker image {self.image_tag} built successfully.")

    def start_container(self, build_path: Path) -> None:
        try:
            subprocess.run(
                ["docker", "container", "inspect", self.container_name],
                check=True,
                capture_output=True,
            )
            self.logger.debug(f"Container {self.container_name} is already running.")
        except subprocess.CalledProcessError:
            args = [
                "docker",
                "run",
                "-d",
                "--name",
                self.container_name,
                "-v",
                f"{build_path}:{self.build_dir}",
                self.image_tag,
                "tail",
                "-f",
                "/dev/null",
            ]
            self.logger.info(
                f"Starting container {self.container_name} with args {' '.join(args)}..."
            )
            subprocess.run(
                args,
                check=True,
                capture_output=True,
            )
            self.logger.info(f"Container {self.container_name} started successfully.")

            # Set the owner of the build directory to the patchwise user
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "--user",
                    "root",
                    self.container_name,
                    "chown",
                    "-R",
                    f"patchwise:patchwise",
                    str(self.build_dir),
                ],
                check=True,
                capture_output=True,
            )

    def run_command(
        self, command: list[str], cwd: Optional[str], **kwargs: Any
    ) -> subprocess.Popen[str]:
        if not cwd:
            cwd = str(self.sandbox_path)

        # Set the owner of the build directory to the patchwise user
        subprocess.run(
            [
                "docker",
                "exec",
                "--user",
                "root",
                self.container_name,
                "chown",
                "-R",
                f"patchwise:patchwise",
                str(self.build_dir),
            ],
            check=True,
            capture_output=True,
        )

        docker_command = ["docker", "exec"]
        docker_command.extend(["--workdir", cwd])
        docker_command.extend([self.container_name] + command)
        self.logger.debug(f"Executing command in container: {' '.join(docker_command)}")
        process = subprocess.Popen(
            docker_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
            **kwargs,
        )
        return process

    def stop_container(self) -> None:
        self.logger.info(f"Stopping container {self.container_name}...")
        subprocess.run(
            ["docker", "stop", self.container_name], check=True, capture_output=True
        )
        subprocess.run(
            ["docker", "rm", self.container_name], check=True, capture_output=True
        )
        self.logger.info(f"Container {self.container_name} stopped and removed.")
