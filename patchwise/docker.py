# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Docker lifecycle management backed by the official Python Docker SDK."""

import logging
import os
import socket
import subprocess
import sys
import threading
import time
import warnings
from collections import deque
from pathlib import Path
from typing import Any, Literal, Optional, Union

import docker
from docker.errors import DockerException, NotFound
from docker.models.containers import Container
from docker.utils.socket import STDERR, STDOUT, frames_iter

from patchwise import PACKAGE_NAME, PACKAGE_PATH
from patchwise.utils.config import parse_config, redis_address
from patchwise.utils.repo_workspace import is_repo_managed, require_workspace_root

_GIT_COMMITTER = parse_config()["git_committer"]


def _error_text(error: BaseException) -> str:
    """Return the useful daemon error text from an SDK exception."""
    return str(getattr(error, "explanation", None) or error).strip()


def _has_cause(error: BaseException, exception_type: type[BaseException]) -> bool:
    """Return whether an exception or one of its causes has the given type."""
    seen: set[int] = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, exception_type):
            return True
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return False


def _docker_error(action: str, error: DockerException) -> RuntimeError:
    """Add operation context while preserving the Docker daemon's detail."""
    return RuntimeError(f"Failed to {action}: {_error_text(error)}")


def check_docker_available() -> None:
    """Fail fast with a clear message if the Docker daemon cannot be used."""
    try:
        docker.from_env().ping()
    except DockerException as error:
        detail = _error_text(error)
        if _has_cause(error, FileNotFoundError):
            sys.exit(
                "Docker is not installed or the Docker socket is unavailable. "
                "Install and start Docker: "
                f"https://docs.docker.com/engine/install/\n{detail}"
            )
        if "permission denied" in detail.lower():
            sys.exit(
                "Permission denied when talking to the Docker daemon. "
                "Add your user to the 'docker' group (sudo usermod -aG docker "
                "$USER, then log out/in) or run patchwise with sufficient "
                f"privileges.\n{detail}"
            )
        sys.exit(
            "Unable to reach the Docker daemon. Ensure Docker is installed and "
            f"running:\n{detail}"
        )


class DockerExecProcess:
    """A temporary, minimal ``Popen`` compatibility layer for SDK execs.

    New callers should use a Docker-specific execution interface when one is
    available. ``kill`` cannot terminate an individual Docker exec, so callers
    must enforce a command timeout inside the container. This wrapper retains
    ``communicate`` only while existing review tools are migrated away from its
    subprocess-shaped API.
    """

    def __init__(
        self,
        manager: "DockerManager",
        command: list[str],
        cwd: str,
        *,
        text: bool = True,
        stdin: Any = None,
        user: Optional[str] = None,
        environment: Optional[dict[str, str]] = None,
    ) -> None:
        self._manager = manager
        self._command = command
        self._cwd = cwd
        self._text = text
        self._stdin = stdin
        self._user = user
        self._environment = environment
        self.returncode: Optional[int] = None
        self._result: tuple[Any, Any] = ("" if text else b"", "" if text else b"")
        self._error: Optional[BaseException] = None
        self._complete = threading.Event()
        self._start_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def _run(self, input: Any) -> None:
        try:
            self.returncode, self._result = self._manager._exec(
                self._command,
                self._cwd,
                input=input,
                text=self._text,
                user=self._user,
                environment=self._environment,
            )
        except Exception as error:
            self._error = error
        finally:
            self._complete.set()

    def communicate(
        self, input: Any = None, timeout: Optional[float] = None
    ) -> tuple[Any, Any]:
        with self._start_lock:
            if self._thread is None:
                if input is not None and self._stdin is None:
                    raise ValueError("stdin was not requested for this command")
                self._thread = threading.Thread(
                    target=self._run, args=(input,), daemon=True
                )
                self._thread.start()
            elif input is not None:
                raise ValueError(
                    "stdin can only be supplied to the first communicate call"
                )
        if not self._complete.wait(timeout):
            raise subprocess.TimeoutExpired(self._command, timeout)
        if self._error is not None:
            raise self._error
        return self._result

    def kill(self) -> None:
        message = (
            "DockerExecProcess.kill() cannot stop an individual Docker exec and "
            "is deprecated; enforce timeouts inside the container instead."
        )
        self._manager.logger.warning(message)
        warnings.warn(message, DeprecationWarning, stacklevel=2)


class DockerManager:
    build_volume_initialized = False
    _build_volume_name = "patchwise-shared-build"
    sandbox_path = Path("/home") / PACKAGE_NAME
    build_dir = sandbox_path / "build"
    kernel_dir = sandbox_path / "kernel"
    # Nothing we run in a container needs network (packages are installed at image
    # build time), and the agent runs model-composed shell commands over an
    # untrusted patch, so denying egress keeps a prompt injection sandboxed.
    _network_mode = "none"

    ts_cache_initialized = False
    _ts_cache_container = "patchwise-ts-cache"
    _ts_cache_volume = "patchwise-ts-cache"
    _ts_cache_container_port = 6379

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
        self.git_subdir = (git_subdir or "").strip("/")
        self._kernel_overlay_volume: Optional[str] = None
        self._container_object: Optional[Container] = None
        self.client = docker.from_env()
        require_workspace_root(str(self.repo_path))
        self._repo_managed = is_repo_managed(str(self.repo_path))

    @property
    def _git_workdir(self) -> str:
        return "/".join(filter(None, [str(self.kernel_dir), self.git_subdir]))

    @property
    def _kernel_volume_name(self) -> str:
        return f"patchwise-kernel-{self.container_name}"

    @property
    def _kernel_backing_volume_name(self) -> str:
        return f"patchwise-kernel-backing-{self.container_name}"

    @staticmethod
    def _mount(source: str, target: str) -> dict[str, dict[str, str]]:
        destination, _, mode = target.partition(":")
        return {source: {"bind": destination, "mode": mode or "ro"}}

    def _setup_kernel_overlay(self) -> str:
        """Create an overlay volume backed by Docker-managed storage.

        The overlay upper and work directories must not depend on the host
        sandbox path, which can be a small tmpfs. Keeping them in a Docker
        volume places the writable overlay data in Docker's persistent storage.
        """
        backing_volume = self._kernel_backing_volume_name
        volume_name = self._kernel_volume_name
        self.logger.debug(
            "Creating kernel overlay backing volume '%s'...", backing_volume
        )
        self.client.volumes.create(backing_volume)
        self.client.containers.run(
            "patchwise-base:latest",
            ["mkdir", "/backing/upper", "/backing/work"],
            remove=True,
            user="root",
            network_mode=self._network_mode,
            volumes=self._mount(backing_volume, "/backing:rw"),
        )
        mountpoint = self.client.volumes.get(backing_volume).attrs["Mountpoint"]
        self.client.volumes.create(
            volume_name,
            driver="local",
            driver_opts={
                "type": "overlay",
                "o": (
                    f"lowerdir={self.repo_path},upperdir={mountpoint}/upper,"
                    f"workdir={mountpoint}/work,metacopy=on"
                ),
                "device": "overlay",
            },
        )
        self.logger.debug("Kernel overlay volume '%s' created.", volume_name)
        return volume_name

    def _cleanup_kernel_overlay(self) -> None:
        for volume in (self._kernel_volume_name, self._kernel_backing_volume_name):
            try:
                self.client.volumes.get(volume).remove(force=True)
            except NotFound:
                continue
            except Exception as error:
                self.logger.warning(
                    "Failed to remove overlay volume %s: %s", volume, _error_text(error)
                )
        self._kernel_overlay_volume = None
        self.logger.debug("Kernel overlay for %s cleaned up.", self.container_name)

    def _build(self, dockerfile: Path, tag: str) -> None:
        """Keep CLI builds for BuildKit and registry-specific credential lookup.

        The SDK's legacy build API loads every configured credential helper,
        so a broken helper for an unrelated registry can prevent all builds.
        Drain output into the file log rather than corrupting the dashboard.
        """
        command = [
            "docker",
            "build",
            "--rm=true",
            "--force-rm=true",
            "-f",
            str(dockerfile),
            "-t",
            tag,
            str(PACKAGE_PATH),
        ]
        output: deque[str] = deque(maxlen=20)
        try:
            with subprocess.Popen(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            ) as process:
                if process.stdout:
                    for line in process.stdout:
                        self.logger.debug(line.rstrip())
                        output.append(line)
                code = process.wait()
                if code:
                    raise RuntimeError(
                        f"Failed to build image {tag} (exit code {code}):\n"
                        + "".join(output).strip()
                    )
            self.client.images.get(tag)
        except DockerException as error:
            raise _docker_error(f"build image {tag}", error) from error
        except FileNotFoundError as error:
            raise RuntimeError(
                "Docker CLI is required to build images. Install Docker: "
                "https://docs.docker.com/engine/install/"
            ) from error
        except OSError as error:
            raise RuntimeError(f"Failed to build image {tag}: {error}") from error

    def build_image(self, dockerfile_path: Path) -> None:
        base_image_tag = "patchwise-base:latest"
        self.logger.info("Building base Docker image %s...", base_image_tag)
        self._build(PACKAGE_PATH / "dockerfiles" / "base.Dockerfile", base_image_tag)
        self.logger.info("Base Docker image %s built successfully.", base_image_tag)
        if self.image_tag != base_image_tag:
            self.logger.info("Building tool-specific image %s...", self.image_tag)
            self._build(dockerfile_path, self.image_tag)
            self.logger.info(
                "Tool-specific image %s built successfully.", self.image_tag
            )

    def _container(self) -> Container:
        if self._container_object is None:
            self._container_object = self.client.containers.get(self.container_name)
        return self._container_object

    def _cleanup_container(self) -> None:
        try:
            self._container().remove(force=True)
        except NotFound:
            pass
        except Exception as error:
            self.logger.warning(
                "Failed to remove container %s: %s",
                self.container_name,
                _error_text(error),
            )
        finally:
            self._container_object = None

    def _start_container(
        self, mounts: dict[str, dict[str, str]], *, reset_tree: bool
    ) -> None:
        try:
            self._cleanup_container()
            self._cleanup_kernel_overlay()
            self._kernel_overlay_volume = self._setup_kernel_overlay()
            mounts.update(
                self._mount(self._kernel_overlay_volume, f"{self.kernel_dir}:rw")
            )
            self.logger.info("Starting container %s...", self.container_name)
            self._container_object = self.client.containers.run(
                self.image_tag,
                ["tail", "-f", "/dev/null"],
                detach=True,
                name=self.container_name,
                network_mode=self._network_mode,
                volumes=mounts,
            )
            self._configure_git_identity()
            self._prepare_kernel_tree(reset_tree=reset_tree)
            self.logger.info("Container %s started successfully.", self.container_name)
        except Exception as error:
            # Preparation may fail after the container has started. Remove it
            # before releasing its overlay volumes, otherwise Docker keeps the
            # volumes in use and teardown leaks both resources.
            self._cleanup_container()
            self._cleanup_kernel_overlay()
            if isinstance(error, DockerException):
                raise _docker_error(
                    f"start container {self.container_name}", error
                ) from error
            raise

    def start_container(
        self,
        mounts: Optional[dict[Path, str]] = None,
        *,
        mount_shared_build: bool = True,
        reset_tree: bool = True,
    ) -> None:
        docker_mounts: dict[str, dict[str, str]] = {}
        if mount_shared_build:
            docker_mounts.update(
                self._mount(self._build_volume_name, f"{self.build_dir}:rw")
            )
        for host, destination in (mounts or {}).items():
            docker_mounts.update(self._mount(str(host), destination))
        # Users are responsible for preparing repo-managed trees for review;
        # resetting them would discard their workspace state.
        self._start_container(
            docker_mounts,
            reset_tree=False if self._repo_managed else reset_tree,
        )
        if mount_shared_build:
            try:
                self._fix_build_directory_permissions()
            except Exception:
                self._cleanup_container()
                self._cleanup_kernel_overlay()
                raise

    def _exec(
        self,
        command: list[str],
        cwd: str,
        *,
        input: Any,
        text: bool,
        user: Optional[str],
        environment: Optional[dict[str, str]],
    ) -> tuple[int, tuple[Any, Any]]:
        container = self._container()
        if input is None:
            result = container.exec_run(
                command, workdir=cwd, user=user, environment=environment, demux=True
            )
            stdout, stderr = result.output or (b"", b"")
            # With demux=True, the SDK uses None for an empty output stream.
            stdout, stderr = stdout or b"", stderr or b""
            code = result.exit_code
        else:
            created = self.client.api.exec_create(
                container.id,
                command,
                stdin=True,
                stdout=True,
                stderr=True,
                workdir=cwd,
                user=user,
                environment=environment,
            )
            exec_id = created["Id"]
            raw_socket = self.client.api.exec_start(exec_id, socket=True)
            sock = getattr(raw_socket, "_sock", raw_socket)
            payload = input.encode() if isinstance(input, str) else input
            write_error: list[Exception] = []

            # Sending stdin and draining stdout/stderr must happen concurrently:
            # a command can produce output before it consumes all its input.
            def write_stdin() -> None:
                try:
                    if payload:
                        sock.sendall(payload)
                    try:
                        sock.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                except Exception as error:
                    write_error.append(error)

            writer = threading.Thread(target=write_stdin)
            writer.start()
            stdout, stderr = bytearray(), bytearray()
            try:
                for stream, data in frames_iter(sock, tty=False):
                    if stream == STDOUT:
                        stdout.extend(data)
                    elif stream == STDERR:
                        stderr.extend(data)
            finally:
                raw_socket.close()
                writer.join()
            if write_error:
                raise write_error[0]
            code = self.client.api.exec_inspect(exec_id)["ExitCode"]
            stdout, stderr = bytes(stdout), bytes(stderr)
        if text:
            return code, (
                stdout.decode(errors="replace"),
                stderr.decode(errors="replace"),
            )
        return code, (stdout, stderr)

    def run_command(
        self, command: list[str], cwd: Optional[str], **kwargs: Any
    ) -> DockerExecProcess:
        cwd = str(cwd or self.sandbox_path)
        text = kwargs.pop("text", True)
        stdin = kwargs.pop("stdin", None)
        user = kwargs.pop("user", None)
        environment = kwargs.pop("environment", None)
        if kwargs:
            unsupported = ", ".join(sorted(kwargs))
            raise TypeError(f"Unsupported Docker exec options: {unsupported}")
        self.logger.debug("Executing command in container: %s", command)
        return DockerExecProcess(
            self,
            command,
            cwd,
            text=text,
            stdin=stdin,
            user=user,
            environment=environment,
        )

    def run_stdin_command(
        self, command: list[str], cwd: Optional[str], **kwargs: Any
    ) -> DockerExecProcess:
        """Run a buffered command whose complete standard input is supplied to communicate.

        Docker SDK exec does not offer the incremental stdio contract implied by
        ``Popen``. Use this method for commands that consume all input before
        producing their result.
        """
        return self.run_command(command, cwd, stdin=subprocess.PIPE, **kwargs)

    def run_interactive_command(
        self, command: list[str], cwd: Optional[str], **kwargs: Any
    ) -> DockerExecProcess:
        """Deprecated alias for :meth:`run_stdin_command`.

        It is buffered, not an incremental interactive stdio session.
        """
        warnings.warn(
            "run_interactive_command() is deprecated; use run_stdin_command() "
            "for buffered standard input.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.run_stdin_command(command, cwd, **kwargs)

    def run_cmd_with_timer(
        self, cmd: list[str], desc: str, cwd: Optional[str] = None, **kwargs: Any
    ) -> str:
        from patchwise.ui import events

        show_timer = (
            self.logger.isEnabledFor(logging.INFO) and not events.has_subscribers()
        )
        start = time.time()
        proc = self.run_command(cmd, cwd=cwd, **kwargs)
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=5)
                if stdout:
                    self.logger.debug(stdout)
                if stderr:
                    self.logger.debug(stderr)
                if show_timer:
                    sys.stdout.write("\r\033[K")
                    sys.stdout.flush()
                break
            except subprocess.TimeoutExpired:
                elapsed = int(time.time() - start)
                if show_timer:
                    sys.stdout.write(f"\r\033[K{desc}... {elapsed}s elapsed")
                    sys.stdout.flush()
        elapsed = int(time.time() - start)
        self.logger.debug("%s completed in %ss", desc, elapsed)
        return (stdout or "") + (stderr or "")

    def read_file(self, path: str) -> Union[str, Literal[False]]:
        proc = self.run_command(["cat", path], cwd=None)
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            self.logger.debug("read_file(%s) failed: %s", path, stderr.strip())
            return False
        return stdout

    def write_file(self, path: str, content: str) -> bool:
        proc = self.run_stdin_command(["tee", path], cwd=None)
        _, stderr = proc.communicate(input=content)
        if proc.returncode != 0:
            self.logger.debug("write_file(%s) failed: %s", path, stderr.strip())
            return False
        return True

    def stop_container(self) -> None:
        self.logger.debug("Stopping container %s...", self.container_name)
        try:
            container = self._container()
            container.stop()
            container.remove()
            self.logger.debug("Container %s stopped and removed.", self.container_name)
        except NotFound:
            self.logger.debug("Container %s was already removed.", self.container_name)
        except DockerException as error:
            raise _docker_error(
                f"stop container {self.container_name}", error
            ) from error
        finally:
            self._container_object = None
            self._cleanup_kernel_overlay()

    @classmethod
    def create_shared_build_volume(cls) -> None:
        client = docker.from_env()
        logger = logging.getLogger(f"{PACKAGE_NAME}.{cls.__name__.lower()}")
        try:
            client.volumes.get(cls._build_volume_name)
            logger.debug("Volume %s already exists.", cls._build_volume_name)
        except NotFound:
            client.volumes.create(cls._build_volume_name)
            logger.debug("Volume %s created successfully.", cls._build_volume_name)

    @classmethod
    def initialize_shared_build_volume(
        cls, repo_path: Path, current_commit_sha: str
    ) -> None:
        del repo_path
        if cls.build_volume_initialized:
            return
        cls.create_shared_build_volume()
        client = docker.from_env()
        logger = logging.getLogger(f"{PACKAGE_NAME}.{cls.__name__.lower()}")
        name = f"patchwise-init-{current_commit_sha[:8]}-{os.getpid()}"
        try:
            try:
                client.containers.get(name).remove(force=True)
            except NotFound:
                pass
            container = client.containers.run(
                "patchwise-base:latest",
                ["tail", "-f", "/dev/null"],
                detach=True,
                name=name,
                network_mode=cls._network_mode,
                volumes=cls._mount(cls._build_volume_name, f"{cls.build_dir}:rw"),
            )
            result = container.exec_run(
                [
                    "sh",
                    "-lc",
                    f"set -e; mkdir -p {cls.build_dir}; chown -R patchwise:patchwise {cls.build_dir}; chmod -R 755 {cls.build_dir}",
                ],
                user="root",
                demux=True,
            )
            if result.exit_code:
                raise RuntimeError(
                    f"Failed to initialize shared build volume: {result.output}"
                )
            cls.build_volume_initialized = True
        finally:
            try:
                client.containers.get(name).remove(force=True)
            except NotFound:
                pass
            except DockerException as error:
                # Preserve an initialization failure; a best-effort cleanup
                # failure should not obscure the operation that caused it.
                logger.warning(
                    "Unable to remove build-volume initialization container %s: %s",
                    name,
                    _error_text(error),
                )

    @classmethod
    def ensure_ts_cache_service(cls) -> None:
        if cls.ts_cache_initialized:
            return
        client = docker.from_env()
        logger = logging.getLogger(f"{PACKAGE_NAME}.{cls.__name__.lower()}")
        try:
            container = client.containers.get(cls._ts_cache_container)
            container.reload()
            if container.status != "running":
                container.start()
        except NotFound:
            host, port = redis_address()
            container = client.containers.run(
                "redis:alpine",
                [
                    "redis-server",
                    "--maxmemory",
                    "5gb",
                    "--maxmemory-policy",
                    "allkeys-lru",
                    "--save",
                    "900 1 300 100",
                    "--dir",
                    "/data",
                ],
                detach=True,
                name=cls._ts_cache_container,
                ports={f"{cls._ts_cache_container_port}/tcp": (host, port)},
                volumes=cls._mount(cls._ts_cache_volume, "/data:rw"),
            )
        cls._wait_ts_cache_ready(container)
        logger.debug("ts-cache container %s started.", cls._ts_cache_container)
        cls.ts_cache_initialized = True

    @classmethod
    def _wait_ts_cache_ready(cls, container: Container, timeout: float = 120) -> None:
        deadline = time.monotonic() + timeout
        while True:
            result = container.exec_run(["redis-cli", "ping"], demux=True)
            stdout, stderr = result.output or (b"", b"")
            stdout, stderr = stdout or b"", stderr or b""
            if stdout.strip() == b"PONG":
                return
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"ts-cache container {cls._ts_cache_container} not ready after {timeout}s: {(stdout + stderr).decode(errors='replace').strip()}"
                )
            time.sleep(1)

    def _run_root(self, command: list[str], *, workdir: Optional[str] = None) -> None:
        result = self._container().exec_run(
            command, user="root", workdir=workdir, demux=True
        )
        if result.exit_code:
            stdout, stderr = result.output or (b"", b"")
            stdout, stderr = stdout or b"", stderr or b""
            raise RuntimeError(
                f"Container command failed ({result.exit_code}): {(stdout + stderr).decode(errors='replace')}"
            )

    def _prepare_kernel_tree(self, *, reset_tree: bool = True) -> None:
        # Trust repositories mounted from the host, whose ownership differs from
        # the container's users.
        self._run_root(["git", "config", "--system", "--add", "safe.directory", "*"])
        if not reset_tree:
            return
        self._run_root(
            ["git", "reset", "--hard", self.commit_sha], workdir=self._git_workdir
        )
        self._run_root(["git", "clean", "-fdx"], workdir=self._git_workdir)
        # Give the agent ownership of the git tree after root performed the reset.
        # TODO: Does resetting outside the container in --mail mode avoid this?
        self._run_root(["chown", "-R", "patchwise:patchwise", self._git_workdir])

    def _configure_git_identity(self) -> None:
        for key, value in (
            ("user.name", _GIT_COMMITTER["name"]),
            ("user.email", _GIT_COMMITTER["email"]),
        ):
            self._run_root(["git", "config", "--system", key, value])

    def _fix_build_directory_permissions(self) -> None:
        if not self.commit_sha:
            self.logger.warning(
                "No commit SHA available, cannot fix build directory permissions"
            )
            return
        # Create and fix permissions for the commit-specific build directory.
        directory = str(self.build_dir / self.commit_sha)
        self._run_root(["mkdir", "-p", directory])
        self._run_root(["chown", "-R", "patchwise:patchwise", directory])
        self._run_root(["chmod", "-R", "755", directory])


# Global tracking for container orchestration
CONTAINERS_BUILT: dict[str, DockerManager] = {}
