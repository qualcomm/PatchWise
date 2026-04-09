# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from patchwise import PACKAGE_NAME, PACKAGE_PATH


class DockerManager:
    # Class-level tracking for initialization
    build_volume_initialized = False
    _build_volume_name = "patchwise-shared-build"

    def __init__(
        self,
        image_tag: str,
        container_name: str,
        repo_path: Path,
        commit_sha: str,
    ):
        self.logger = logging.getLogger(
            f"{PACKAGE_NAME}.{self.__class__.__name__.lower()}"
        )
        self.image_tag = image_tag
        self.container_name = container_name
        self.repo_path = repo_path.resolve()
        self.commit_sha = commit_sha
        self.sandbox_path = Path("/home") / PACKAGE_NAME
        self.build_dir = self.sandbox_path / "build"
        self.kernel_dir = self.sandbox_path / "kernel"

    @property
    def _kernel_volume_name(self) -> str:
        """Docker volume name for this container's kernel overlay."""
        return f"patchwise-kernel-{self.container_name}"

    @property
    def _kernel_backing_volume_name(self) -> str:
        """Docker volume name for this container's overlay backing storage (upper/work)."""
        return f"patchwise-kernel-backing-{self.container_name}"

    def _setup_kernel_overlay(self) -> str:
        """Create a Docker volume with overlay driver options.

        Uses a Docker backing volume to hold the overlay upper/work
        directories, avoiding any dependency on the host SANDBOX_PATH (which
        may be a small tmpfs).  A helper container initialises the scratch
        directories inside the backing volume; Docker then creates a second
        local volume of type overlay that uses those paths as upperdir/workdir.

        The working/merged directories for the overlay stay on the host inside
        Docker's own volume storage, which is typically on a large persistent
        filesystem rather than a tmpfs.

        Returns the Docker overlay volume name.
        """
        backing_volume = self._kernel_backing_volume_name
        volume_name = self._kernel_volume_name

        # Remove stale volumes with the same names (if any) so we always get
        # a fresh overlay.
        for vol in (volume_name, backing_volume):
            subprocess.run(["docker", "volume", "rm", "-f", vol])

        # Create the backing volume that will hold upper/ and work/.
        self.logger.info(
            f"Creating kernel overlay backing volume '{backing_volume}' "
            f"for {self.container_name}..."
        )
        subprocess.run(
            ["docker", "volume", "create", backing_volume],
            check=True,
            capture_output=True,
        )

        # Initialise the scratch directories inside the backing volume using a
        # short-lived helper container.
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                "root",
                "-v",
                f"{backing_volume}:/backing",
                "patchwise-base:latest",
                "mkdir",
                "/backing/upper",
                "/backing/work",
            ],
            check=True,
            capture_output=True,
        )

        # Resolve the backing volume's host mountpoint so we can pass absolute
        # paths to the overlay mount options.
        result = subprocess.run(
            [
                "docker",
                "volume",
                "inspect",
                backing_volume,
                "-f",
                "{{.Mountpoint}}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        backing_mountpoint = result.stdout.strip()
        upper = f"{backing_mountpoint}/upper"
        work = f"{backing_mountpoint}/work"

        self.logger.info(
            f"Creating kernel overlay volume '{volume_name}' for {self.container_name}..."
        )
        subprocess.run(
            [
                "docker",
                "volume",
                "create",
                "--driver",
                "local",
                "--opt",
                "type=overlay",
                "--opt",
                f"o=lowerdir={self.repo_path},upperdir={upper},workdir={work},metacopy=on",
                "--opt",
                "device=overlay",
                volume_name,
            ],
            check=True,
            capture_output=True,
        )
        self.logger.info(f"Kernel overlay volume '{volume_name}' created.")
        return volume_name

    def _cleanup_kernel_overlay(self) -> None:
        """Remove the Docker overlay volume and backing volume for this container."""
        for vol in (self._kernel_volume_name, self._kernel_backing_volume_name):
            subprocess.run(["docker", "volume", "rm", "-f", vol])
        self.logger.info(f"Kernel overlay for {self.container_name} cleaned up.")

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

    def build_image(self, dockerfile_path: Path) -> None:
        base_image_tag = "patchwise-base:latest"

        # Stage 1: Build base image
        self.logger.info(f"Building base Docker image {base_image_tag}...")
        base_dockerfile = PACKAGE_PATH / "dockerfiles" / "base.Dockerfile"
        process = subprocess.Popen(
            [
                "docker",
                "build",
                "-f",
                str(base_dockerfile),
                "-t",
                base_image_tag,
                str(PACKAGE_PATH),
            ],
            text=True,
        )
        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, process.args)
        self.logger.info(f"Base Docker image {base_image_tag} built successfully.")

        # Stage 2: Build tool-specific image (if not base)
        if self.image_tag != base_image_tag:
            self.logger.info(f"Building tool-specific image {self.image_tag}...")
            process = subprocess.Popen(
                [
                    "docker",
                    "build",
                    "-f",
                    str(dockerfile_path),
                    "-t",
                    self.image_tag,
                    str(PACKAGE_PATH),
                ],
                text=True,
            )
            process.wait()
            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, process.args)
            self.logger.info(
                f"Tool-specific image {self.image_tag} built successfully."
            )

    def start_container(self, build_path: Path) -> None:
        """Legacy method for backward compatibility. Use start_container_with_shared_volume instead."""
        try:
            self._kernel_overlay_volume = self._setup_kernel_overlay()
        except subprocess.CalledProcessError as e:
            self.logger.error(
                f"Failed to create kernel overlay volume: {e}\nstderr:{e.stderr}"
            )
            raise

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
                "-v",
                f"{self._kernel_overlay_volume}:{self.kernel_dir}",
                self.image_tag,
                "tail",
                "-f",
                "/dev/null",
            ]
            self.logger.info(
                f"Starting container {self.container_name} with args {' '.join(args)}..."
            )
            try:
                subprocess.run(
                    args,
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                self.logger.info(
                    f"Failed to start container {self.container_name}: {e}\nstderr: {e.stderr}"
                )
                self._cleanup_kernel_overlay()
                raise
            self.logger.info(f"Container {self.container_name} started successfully.")

            try:
                self._prepare_kernel_tree()
            except subprocess.CalledProcessError as e:
                self.logger.error(
                    f"Failed to prepare kernel tree at {self.commit_sha}: {e}\nstderr: {e.stderr}"
                )
                self._cleanup_kernel_overlay()
                raise

    def run_command(
        self, command: list[str], cwd: Optional[str], **kwargs: Any
    ) -> subprocess.Popen[str]:
        if not cwd:
            cwd = str(self.sandbox_path)

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

    def run_interactive_command(
        self, command: list[str], cwd: Optional[str], **kwargs: Any
    ) -> subprocess.Popen[str]:
        """Run an interactive command that needs stdin/stdout communication."""
        if not cwd:
            cwd = str(self.sandbox_path)

        docker_command = ["docker", "exec", "-i"]
        docker_command.extend(["--workdir", cwd])
        docker_command.extend([self.container_name] + command)
        self.logger.debug(
            f"Executing interactive command in container: {' '.join(docker_command)}"
        )
        process = subprocess.Popen(
            docker_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=0,  # Unbuffered for real-time LSP communication
            universal_newlines=True,
            **kwargs,
        )
        return process

    def ensure_clangd_index_dir(self) -> None:
        """Ensure clangd index directory exists in build volume with proper permissions."""
        index_dir = self.build_dir / ".clangd"

        self.logger.debug(f"Ensuring clangd index directory: {index_dir}")

        # Create index directory in container
        create_proc = self.run_command(
            ["mkdir", "-p", str(index_dir)], cwd=str(self.build_dir)
        )
        create_proc.wait()

        if create_proc.returncode != 0:
            self.logger.warning(f"Failed to create clangd index directory: {index_dir}")
            return

        # Fix permissions as root
        try:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "--user",
                    "root",
                    self.container_name,
                    "chown",
                    "-R",
                    "patchwise:patchwise",
                    str(index_dir),
                ],
                check=True,
                capture_output=True,
            )

            subprocess.run(
                [
                    "docker",
                    "exec",
                    "--user",
                    "root",
                    self.container_name,
                    "chmod",
                    "-R",
                    "755",
                    str(index_dir),
                ],
                check=True,
                capture_output=True,
            )

            self.logger.debug(
                f"Fixed permissions for clangd index directory: {index_dir}"
            )
        except subprocess.CalledProcessError as e:
            self.logger.warning(
                f"Failed to fix permissions for clangd index directory: {e}\nstderr: {e.stderr}"
            )

    def start_clangd_lsp(
        self, clangd_args: list[str], cwd: Optional[str] = None
    ) -> subprocess.Popen[str]:
        """Start clangd via docker exec with direct stdin/stdout communication."""
        if not cwd:
            cwd = str(self.kernel_dir)

        # Ensure index directory exists
        self.ensure_clangd_index_dir()

        self.logger.debug(
            f"Starting clangd LSP server with args: {' '.join(clangd_args)}"
        )
        self.logger.debug(f"Working directory: {cwd}")
        self.logger.debug(f"Container name: {self.container_name}")

        # Use docker exec -i for interactive communication
        docker_command = [
            "docker",
            "exec",
            "-i",
            "--workdir",
            cwd,
            self.container_name,
        ] + clangd_args

        self.logger.debug(f"Docker command: {' '.join(docker_command)}")

        process = subprocess.Popen(
            docker_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=0,  # Unbuffered for real-time LSP communication
            universal_newlines=True,
        )

        self.logger.debug(f"clangd LSP server started with PID: {process.pid}")

        # Give clangd a moment to start and check if it's still running
        time.sleep(1)
        if process.poll() is not None:
            # Process died immediately, read stderr for debugging
            stderr_output = (
                process.stderr.read() if process.stderr else "No stderr available"
            )
            self.logger.error(
                f"clangd process died immediately with return code {process.returncode}"
            )
            self.logger.error(f"clangd stderr: {stderr_output}")
            raise RuntimeError(f"clangd failed to start: {stderr_output}")

        return process

    def cleanup_clangd(self) -> None:
        """Clean up any running clangd processes in the container."""
        try:
            # Kill any existing clangd processes
            subprocess.run(
                ["docker", "exec", self.container_name, "pkill", "-f", "clangd"],
                capture_output=True,
            )
            self.logger.debug("Cleaned up existing clangd processes")
        except Exception as e:
            self.logger.debug(f"No clangd processes to clean up: {e}")

    def stop_container(self) -> None:
        self.logger.info(f"Stopping container {self.container_name}...")
        try:
            subprocess.run(
                ["docker", "stop", self.container_name],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["docker", "rm", self.container_name],
                check=True,
                capture_output=True,
            )
            self.logger.info(f"Container {self.container_name} stopped and removed.")
        except subprocess.CalledProcessError as e:
            self.logger.error(
                f"Failed to stop container {self.container_name}: {e}\nstderr: {e.stderr}"
            )
            raise
        finally:
            self._cleanup_kernel_overlay()

    @classmethod
    def create_shared_build_volume(cls) -> None:
        """Create the shared build volume if it doesn't exist."""
        logger = logging.getLogger(f"{PACKAGE_NAME}.{cls.__name__.lower()}")

        # Check if volume already exists
        try:
            subprocess.run(
                ["docker", "volume", "inspect", cls._build_volume_name],
                check=True,
                capture_output=True,
            )
            logger.debug(f"Volume {cls._build_volume_name} already exists.")
            return
        except subprocess.CalledProcessError:
            # Volume doesn't exist, create it
            logger.info(f"Creating shared build volume {cls._build_volume_name}...")
            subprocess.run(
                ["docker", "volume", "create", cls._build_volume_name],
                check=True,
                capture_output=True,
            )
            logger.info(f"Volume {cls._build_volume_name} created successfully.")

    @classmethod
    def initialize_shared_build_volume(
        cls, repo_path: Path, current_commit_sha: str
    ) -> None:
        """Initialize the shared build volume using the base container."""
        logger = logging.getLogger(f"{PACKAGE_NAME}.{cls.__name__.lower()}")

        if cls.build_volume_initialized:
            logger.debug("Build volume already initialized, skipping.")
            return

        logger.info("Initializing shared build volume...")

        # Ensure the volume exists
        cls.create_shared_build_volume()

        # Create a temporary base container to initialize the volume
        base_image_tag = "patchwise-base:latest"
        init_container_name = f"patchwise-init-{current_commit_sha[:8]}"

        try:
            # Start container with the shared volume mounted
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    init_container_name,
                    "-v",
                    f"{cls._build_volume_name}:/shared/build",
                    base_image_tag,
                    "tail",
                    "-f",
                    "/dev/null",
                ],
                check=True,
                capture_output=True,
            )

            # Run the initialization script as root
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "--user",
                    "root",
                    init_container_name,
                    "/home/patchwise/init-build-dir.sh",
                ],
                check=True,
                capture_output=True,
            )

            logger.info("Shared build volume initialized successfully.")
            cls.build_volume_initialized = True

        finally:
            # Clean up the temporary container
            try:
                subprocess.run(
                    ["docker", "stop", init_container_name],
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    ["docker", "rm", init_container_name],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError:
                logger.warning(
                    f"Failed to clean up initialization container {init_container_name}"
                )

    def start_container_with_shared_volume(self) -> None:
        """Start container with the shared build volume instead of bind mount."""
        try:
            self._kernel_overlay_volume = self._setup_kernel_overlay()
        except subprocess.CalledProcessError as e:
            self.logger.error(
                f"Failed to create kernel overlay volume: {e}\nstderr:{e.stderr}"
            )
            raise

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
                f"{self._build_volume_name}:/shared/build",
                "-v",
                f"{self._build_volume_name}:{self.build_dir}",
                "-v",
                f"{self._kernel_overlay_volume}:{self.kernel_dir}",
                self.image_tag,
                "tail",
                "-f",
                "/dev/null",
            ]
            self.logger.info(
                f"Starting container {self.container_name} with shared volume..."
            )
            try:
                subprocess.run(
                    args,
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                self.logger.info(
                    f"Failed to start container {self.container_name}: {e}\nstderr: {e.stderr}"
                )
                self._cleanup_kernel_overlay()
                raise
            self.logger.info(f"Container {self.container_name} started successfully.")

            # Ensure the specific build directory has proper permissions
            try:
                self._fix_build_directory_permissions()
            except subprocess.CalledProcessError as e:
                self.logger.error(
                    f"Failed to fix build directory permissions: {e}\nstderr: {e.stderr}"
                )
                self._cleanup_kernel_overlay()
                raise

            try:
                self._prepare_kernel_tree()
            except subprocess.CalledProcessError as e:
                self.logger.error(
                    f"Failed to prepare kernel tree at {self.commit_sha}: {e}\nstderr: {e.stderr}"
                )
                self._cleanup_kernel_overlay()
                raise

    def _prepare_kernel_tree(self) -> None:
        """Set git safe.directory and reset the kernel tree to the target commit."""
        self.logger.debug(
            f"Preparing kernel tree at {self.commit_sha} in {self.container_name}..."
        )
        subprocess.run(
            [
                "docker",
                "exec",
                "--user",
                "root",
                "--workdir",
                str(self.kernel_dir),
                self.container_name,
                "git",
                "config",
                "--global",
                "--add",
                "safe.directory",
                str(self.kernel_dir),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "docker",
                "exec",
                "--user",
                "root",
                "--workdir",
                str(self.kernel_dir),
                self.container_name,
                "git",
                "reset",
                "--hard",
                self.commit_sha,
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "docker",
                "exec",
                "--user",
                "root",
                "--workdir",
                str(self.kernel_dir),
                self.container_name,
                "git",
                "clean",
                "-fdx",
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "docker",
                "exec",
                "--user",
                "root",
                self.container_name,
                "chown",
                "-R",
                "patchwise:patchwise",
                str(self.kernel_dir),
            ],
            check=True,
            capture_output=True,
        )
        self.logger.debug(f"Kernel tree at {self.commit_sha} prepared.")

    def _fix_build_directory_permissions(self) -> None:
        """Fix permissions for the specific build directory inside the container."""
        if not self.commit_sha:
            self.logger.warning(
                "No commit SHA available, cannot fix build directory permissions"
            )
            return

        # Create and fix permissions for the commit-specific directory
        subprocess.run(
            [
                "docker",
                "exec",
                "--user",
                "root",
                self.container_name,
                "mkdir",
                "-p",
                f"/shared/build/{self.commit_sha}",
            ],
            check=True,
            capture_output=True,
        )

        subprocess.run(
            [
                "docker",
                "exec",
                "--user",
                "root",
                self.container_name,
                "chown",
                "-R",
                "patchwise:patchwise",
                f"/shared/build/{self.commit_sha}",
            ],
            check=True,
            capture_output=True,
        )

        subprocess.run(
            [
                "docker",
                "exec",
                "--user",
                "root",
                self.container_name,
                "chmod",
                "-R",
                "755",
                f"/shared/build/{self.commit_sha}",
            ],
            check=True,
            capture_output=True,
        )

        self.logger.debug(f"Fixed permissions for build directory: {self.commit_sha}")


# Global tracking for container orchestration
CONTAINERS_BUILT: dict[str, DockerManager] = {}
