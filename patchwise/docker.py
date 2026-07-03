# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, List, Literal, Optional, Union

from patchwise import PACKAGE_NAME, PACKAGE_PATH
from patchwise.utils.config import parse_config
from patchwise.utils.repo_workspace import is_repo_managed, require_workspace_root

_GIT_COMMITTER = parse_config()["git_committer"]


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
        git_subdir: str = "",
    ):
        self.logger = logging.getLogger(
            f"{PACKAGE_NAME}.{self.__class__.__name__.lower()}"
        )
        self.image_tag = image_tag
        self.container_name = container_name
        self.repo_path = repo_path.resolve()
        self.commit_sha = commit_sha
        # The mounted tree (`repo_path`) is what the agent navigates; the git tree
        # the prep operates on may be a subdirectory of it (e.g. `--repo-path
        # kernel_platform --project common`). Empty => the mount root is the git
        # tree (the common case), so existing callers are unchanged.
        self.git_subdir = (git_subdir or "").strip("/")
        self.sandbox_path = Path("/home") / PACKAGE_NAME
        self.build_dir = self.sandbox_path / "build"
        self.kernel_dir = self.sandbox_path / "kernel"
        self._kernel_overlay_volume: Optional[str] = None
        require_workspace_root(str(self.repo_path))
        self._repo_managed = is_repo_managed(str(self.repo_path))

    @property
    def _git_workdir(self) -> str:
        """In-container path of the git tree (the mount root, or a subdir)."""
        return "/".join(filter(None, [str(self.kernel_dir), self.git_subdir]))

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
            subprocess.run(["docker", "volume", "rm", "-f", vol], capture_output=True)

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
            subprocess.run(
                ["docker", "volume", "rm", "-f", vol],
                capture_output=True,
                start_new_session=True,
            )
        self.logger.debug(f"Kernel overlay for {self.container_name} cleaned up.")

    def _stream_build_output(self, process: subprocess.Popen[str]) -> None:
        """Drain the build's merged stdout/stderr through the logger at debug
        level so the docker build progress is captured in the file log but never
        written to the console (it would otherwise corrupt the live dashboard)."""
        if process.stdout:
            for line in iter(process.stdout.readline, ""):
                self.logger.debug(line.rstrip())
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
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self._stream_build_output(process)
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
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self._stream_build_output(process)
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
                self.logger.error(
                    f"Failed to start container {self.container_name}: {e}\nstderr: {e.stderr}"
                )
                self._cleanup_kernel_overlay()
                raise
            self.logger.info(f"Container {self.container_name} started successfully.")

            try:
                self._configure_git_identity()
            except subprocess.CalledProcessError as e:
                self.logger.error(
                    f"Failed to configure git identity: {e}\nstderr: {e.stderr}"
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

    def run_command(
        self, command: list[str], cwd: Optional[str], **kwargs: Any
    ) -> subprocess.Popen[str]:
        if not cwd:
            cwd = str(self.sandbox_path)
        else:
            cwd = str(cwd)

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
        # Suppress the inline stdout timer while the live dashboard owns the
        # terminal; its own activity spinner covers the work-in-progress feel.
        from patchwise.ui import events

        show_timer = self.logger.isEnabledFor(logging.INFO) and not events.has_subscribers()
        start = time.time()

        process = self.run_command(cmd, cwd=cwd, **kwargs)

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

    def run_interactive_command(
        self, command: list[str], cwd: Optional[str], **kwargs: Any
    ) -> subprocess.Popen[str]:
        """Run an interactive command that needs stdin/stdout communication."""
        if not cwd:
            cwd = str(self.sandbox_path)
        else:
            cwd = str(cwd)

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
            bufsize=0,  # Unbuffered for real-time stdin/stdout JSON-RPC
            universal_newlines=True,
            **kwargs,
        )
        return process

    def read_file(self, path: str) -> Union[str, Literal[False]]:
        """Read a file from inside the container. Returns False on failure."""
        proc = self.run_command(["cat", path], cwd=None)
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            self.logger.debug(f"read_file({path}) failed: {stderr.strip()}")
            return False
        return stdout

    def write_file(self, path: str, content: str) -> bool:
        """Write content to a file inside the container. Returns True on success."""
        proc = self.run_interactive_command(["tee", path], cwd=None)
        _stdout, stderr = proc.communicate(input=content)
        if proc.returncode != 0:
            self.logger.debug(f"write_file({path}) failed: {stderr.strip()}")
            return False
        return True

    def stop_container(self) -> None:
        self.logger.debug(f"Stopping container {self.container_name}...")
        try:
            # start_new_session: run teardown in its own process group so a
            # spammed Ctrl-C (delivered to the foreground group) cannot kill
            # these docker commands mid-cleanup and leak the container/volumes.
            # (subprocess restores SIGINT to SIG_DFL in children by default, so
            # the parent's SIG_IGN alone does not protect them.)
            subprocess.run(
                ["docker", "stop", self.container_name],
                check=True,
                capture_output=True,
                start_new_session=True,
            )
            subprocess.run(
                ["docker", "rm", self.container_name],
                check=True,
                capture_output=True,
                start_new_session=True,
            )
            self.logger.debug(f"Container {self.container_name} stopped and removed.")
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

            # Initialize the shared volume inline instead of depending on a
            # helper script being present in the image.
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "--user",
                    "root",
                    init_container_name,
                    "sh",
                    "-lc",
                    (
                        "set -e; "
                        "echo 'Initializing shared build directory...'; "
                        "mkdir -p /shared/build; "
                        "chown -R patchwise:patchwise /shared/build; "
                        "chmod -R 755 /shared/build; "
                        "echo 'Build directory initialized successfully'"
                    ),
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
            ]
            args += [
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
                self.logger.error(
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
                self._configure_git_identity()
            except subprocess.CalledProcessError as e:
                self.logger.error(
                    f"Failed to configure git identity: {e}\nstderr: {e.stderr}"
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
        """Configure git trust and, for standalone (upstream) kernels, reset the
        tree to the commit under review.

        Skipped for downstream repo(1) workspaces: the caller already checked out
        the change and only the read-only AiCodeReview runs. (The tree is an
        overlay, so reset/clean/chown never reach the caller's on-disk tree.)"""
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
                self._git_workdir,
                self.container_name,
                "git",
                "config",
                "--global",
                "--add",
                "safe.directory",
                self._git_workdir,
            ],
            check=True,
            capture_output=True,
        )

        # Downstream: the tree is left as mounted (foreign-owned, never chowned)
        # and git runs as the agent user across projects, so trust every store.
        if self._repo_managed:
            subprocess.run(
                [
                    "docker", "exec", "--user", "root",
                    self.container_name, "git", "config", "--system",
                    "--add", "safe.directory", "*",
                ],
                check=True,
                capture_output=True,
            )
            self.logger.debug(
                "repo-managed workspace: leaving tree as mounted (read-only)."
            )
            return

        subprocess.run(
            [
                "docker",
                "exec",
                "--user",
                "root",
                "--workdir",
                self._git_workdir,
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
                self._git_workdir,
                self.container_name,
                "git",
                "clean",
                "-fdx",
            ],
            check=True,
            capture_output=True,
        )
        # Give the agent ownership of the git tree (where git wrote during reset).
        # Only the project subtree is chown'd, not the whole mount: when repo_path
        # is a broad workspace, recursively chowning every sibling project would be
        # huge and pointless — kernel source is world-readable, so the agent reads
        # siblings (e.g. out-of-tree modules) without owning them.
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
                self._git_workdir,
            ],
            check=True,
            capture_output=True,
        )
        self.logger.debug(f"Kernel tree at {self.commit_sha} prepared.")

    def _configure_git_identity(self) -> None:
        """Set a system-wide git committer identity inside the container so
        ``git commit --amend`` and similar operations don't fail with
        'empty ident'."""
        for key, value in (
            ("user.name", _GIT_COMMITTER["name"]),
            ("user.email", _GIT_COMMITTER["email"]),
        ):
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "--user",
                    "root",
                    self.container_name,
                    "git",
                    "config",
                    "--system",
                    key,
                    value,
                ],
                check=True,
                capture_output=True,
            )

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
