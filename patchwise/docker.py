# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Docker lifecycle management backed by the official Python Docker SDK."""

import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal, Optional, Union

import docker
from docker.errors import APIError, DockerException, NotFound
from docker.models.containers import Container

from patchwise import PACKAGE_NAME, PACKAGE_PATH
from patchwise.utils.config import parse_config, redis_address
from patchwise.utils.repo_workspace import is_repo_managed, require_workspace_root

_GIT_COMMITTER = parse_config()["git_committer"]


def _error_text(error: BaseException) -> str:
    """Return the useful daemon error text from an SDK exception."""
    return str(getattr(error, "explanation", error)).strip()


def check_docker_available() -> None:
    """Fail fast with a clear message if the Docker daemon cannot be used."""
    try:
        docker.from_env().ping()
    except DockerException as error:
        detail = _error_text(error)
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
    """A small ``Popen``-compatible result object for a Docker SDK exec.

    Keeping this interface avoids forcing all review tools to know whether their
    command runs locally or in a container.  SDK execs are synchronous, so the
    command is run when ``communicate`` is called; this also lets commands that
    need stdin provide it there, as they did with ``subprocess.Popen``.
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

    def communicate(self, input: Any = None, timeout: Optional[float] = None) -> tuple[Any, Any]:
        # Timeout is retained for Popen compatibility. Commands that need a hard
        # limit use the in-container `timeout` utility, so daemon-side exec does
        # not leave work running when a host-side client is interrupted.
        del timeout
        if self.returncode is None:
            self.returncode, self._result = self._manager._exec(
                self._command,
                self._cwd,
                input=input,
                text=self._text,
                user=self._user,
                environment=self._environment,
            )
        return self._result

    def kill(self) -> None:
        # Docker's API has no per-exec kill endpoint.  Timed agent commands are
        # guarded in-container; retain this no-op for callers handling Popen.
        return None


class DockerManager:
    build_volume_initialized = False
    _build_volume_name = "patchwise-shared-build"
    sandbox_path = Path("/home") / PACKAGE_NAME
    build_dir = sandbox_path / "build"
    kernel_dir = sandbox_path / "kernel"
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
        self.logger = logging.getLogger(f"{PACKAGE_NAME}.{self.__class__.__name__.lower()}")
        self.image_tag = image_tag
        self.container_name = container_name
        self.repo_path = repo_path.resolve()
        self.commit_sha = commit_sha
        self.git_subdir = (git_subdir or "").strip("/")
        self._kernel_overlay_volume: Optional[str] = None
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
        return {source: {"bind": destination, "mode": mode or "rw"}}

    def _remove_volume(self, name: str) -> None:
        try:
            self.client.volumes.get(name).remove(force=True)
        except NotFound:
            pass

    def _setup_kernel_overlay(self) -> str:
        backing_volume = self._kernel_backing_volume_name
        volume_name = self._kernel_volume_name
        for volume in (volume_name, backing_volume):
            self._remove_volume(volume)

        self.logger.debug("Creating kernel overlay backing volume '%s'...", backing_volume)
        try:
            self.client.volumes.create(backing_volume)
            self.client.containers.run(
                "patchwise-base:latest",
                ["mkdir", "/backing/upper", "/backing/work"],
                remove=True,
                user="root",
                network_mode=self._network_mode,
                volumes=self._mount(backing_volume, "/backing"),
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
        except Exception:
            # _start_container records the overlay only after this method
            # returns, so clean up partial creation locally on every failure.
            for volume in (volume_name, backing_volume):
                try:
                    self._remove_volume(volume)
                except DockerException:
                    pass
            raise
        self.logger.debug("Kernel overlay volume '%s' created.", volume_name)
        return volume_name

    def _cleanup_kernel_overlay(self) -> None:
        for volume in (self._kernel_volume_name, self._kernel_backing_volume_name):
            try:
                self._remove_volume(volume)
            except APIError as error:
                self.logger.warning("Failed to remove overlay volume %s: %s", volume, _error_text(error))
        self.logger.debug("Kernel overlay for %s cleaned up.", self.container_name)

    def _build(self, dockerfile: Path, tag: str) -> None:
        image, logs = self.client.images.build(dockerfile=str(dockerfile), tag=tag, path=str(PACKAGE_PATH))
        for entry in logs:
            message = entry.get("stream") or entry.get("status") or entry.get("error")
            if message:
                self.logger.debug(message.rstrip())
        if image is None:
            raise RuntimeError(f"Docker did not produce image {tag}")

    def build_image(self, dockerfile_path: Path) -> None:
        base_image_tag = "patchwise-base:latest"
        self.logger.info("Building base Docker image %s...", base_image_tag)
        self._build(PACKAGE_PATH / "dockerfiles" / "base.Dockerfile", base_image_tag)
        self.logger.info("Base Docker image %s built successfully.", base_image_tag)
        if self.image_tag != base_image_tag:
            self.logger.info("Building tool-specific image %s...", self.image_tag)
            self._build(dockerfile_path, self.image_tag)
            self.logger.info("Tool-specific image %s built successfully.", self.image_tag)

    def _container(self) -> Container:
        return self.client.containers.get(self.container_name)

    def _start_container(self, mounts: dict[str, dict[str, str]], *, reset_tree: bool) -> None:
        try:
            self._kernel_overlay_volume = self._setup_kernel_overlay()
            try:
                self._container().remove(force=True)
            except NotFound:
                pass
            mounts.update(self._mount(self._kernel_overlay_volume, str(self.kernel_dir)))
            self.logger.info("Starting container %s...", self.container_name)
            self.client.containers.run(
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
        except Exception:
            # Preparation may fail after the container has started. Remove it
            # before releasing its overlay volumes, otherwise Docker keeps the
            # volumes in use and teardown leaks both resources.
            try:
                self._container().remove(force=True)
            except (DockerException, NotFound):
                pass
            self._cleanup_kernel_overlay()
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
            docker_mounts.update(self._mount(self._build_volume_name, str(self.build_dir)))
        for host, destination in (mounts or {}).items():
            docker_mounts.update(self._mount(str(host), destination))
        self._start_container(docker_mounts, reset_tree=False if self._repo_managed else reset_tree)
        if mount_shared_build:
            try:
                self._fix_build_directory_permissions()
            except Exception:
                try:
                    self._container().remove(force=True)
                except (DockerException, NotFound):
                    pass
                self._cleanup_kernel_overlay()
                raise

    @staticmethod
    def _decode_frames(data: bytes) -> tuple[bytes, bytes]:
        """Decode Docker's non-TTY multiplexed stdout/stderr stream."""
        stdout, stderr, offset = bytearray(), bytearray(), 0
        while offset + 8 <= len(data):
            stream, size = data[offset], int.from_bytes(data[offset + 4 : offset + 8], "big")
            offset += 8
            payload = data[offset : offset + size]
            offset += size
            (stdout if stream == 1 else stderr).extend(payload)
        return bytes(stdout), bytes(stderr)

    def _exec(
        self, command: list[str], cwd: str, *, input: Any, text: bool,
        user: Optional[str], environment: Optional[dict[str, str]],
    ) -> tuple[int, tuple[Any, Any]]:
        container = self._container()
        if input is None:
            result = container.exec_run(command, workdir=cwd, user=user, environment=environment, demux=True)
            stdout, stderr = result.output or (b"", b"")
            # With demux=True, the SDK uses None for an empty output stream.
            stdout, stderr = stdout or b"", stderr or b""
            code = result.exit_code
        else:
            created = self.client.api.exec_create(
                container.id, command, stdin=True, stdout=True, stderr=True,
                workdir=cwd, user=user, environment=environment,
            )
            exec_id = created["Id"]
            raw_socket = self.client.api.exec_start(exec_id, socket=True)
            sock = getattr(raw_socket, "_sock", raw_socket)
            payload = input.encode() if isinstance(input, str) else input
            if payload:
                sock.sendall(payload)
            try:
                sock.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            chunks: list[bytes] = []
            try:
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
            finally:
                raw_socket.close()
            stdout, stderr = self._decode_frames(b"".join(chunks))
            code = self.client.api.exec_inspect(exec_id)["ExitCode"]
        if text:
            return code, (stdout.decode(errors="replace"), stderr.decode(errors="replace"))
        return code, (stdout, stderr)

    def run_command(self, command: list[str], cwd: Optional[str], **kwargs: Any) -> DockerExecProcess:
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
            self, command, cwd, text=text, stdin=stdin, user=user, environment=environment,
        )

    def run_interactive_command(self, command: list[str], cwd: Optional[str], **kwargs: Any) -> DockerExecProcess:
        return self.run_command(command, cwd, stdin=subprocess.PIPE, **kwargs)

    def run_cmd_with_timer(self, cmd: list[str], desc: str, cwd: Optional[str] = None, **kwargs: Any) -> str:
        from patchwise.ui import events
        start = time.time()
        proc = self.run_command(cmd, cwd=cwd, **kwargs)
        stdout, stderr = proc.communicate()
        if self.logger.isEnabledFor(logging.INFO) and not events.has_subscribers():
            sys.stdout.write("\r\033[K")
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
        proc = self.run_interactive_command(["tee", path], cwd=None)
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
        finally:
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
    def initialize_shared_build_volume(cls, repo_path: Path, current_commit_sha: str) -> None:
        del repo_path
        if cls.build_volume_initialized:
            return
        cls.create_shared_build_volume()
        client = docker.from_env()
        name = f"patchwise-init-{current_commit_sha[:8]}-{os.getpid()}"
        try:
            try:
                client.containers.get(name).remove(force=True)
            except NotFound:
                pass
            container = client.containers.run(
                "patchwise-base:latest", ["tail", "-f", "/dev/null"], detach=True, name=name,
                network_mode=cls._network_mode,
                volumes=cls._mount(cls._build_volume_name, str(cls.build_dir)),
            )
            result = container.exec_run(
                ["sh", "-lc", f"set -e; mkdir -p {cls.build_dir}; chown -R patchwise:patchwise {cls.build_dir}; chmod -R 755 {cls.build_dir}"],
                user="root", demux=True,
            )
            if result.exit_code:
                raise RuntimeError(f"Failed to initialize shared build volume: {result.output}")
            cls.build_volume_initialized = True
        finally:
            try:
                client.containers.get(name).remove(force=True)
            except NotFound:
                pass

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
                "redis:alpine", ["redis-server", "--maxmemory", "5gb", "--maxmemory-policy", "allkeys-lru", "--save", "900 1 300 100", "--dir", "/data"],
                detach=True, name=cls._ts_cache_container,
                ports={f"{cls._ts_cache_container_port}/tcp": (host, port)},
                volumes=cls._mount(cls._ts_cache_volume, "/data"),
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
            if stdout.strip() == b"PONG":
                return
            if time.monotonic() > deadline:
                raise RuntimeError(f"ts-cache container {cls._ts_cache_container} not ready after {timeout}s: {(stdout + stderr).decode(errors='replace').strip()}")
            time.sleep(1)

    def _run_root(self, command: list[str], *, workdir: Optional[str] = None) -> None:
        result = self._container().exec_run(command, user="root", workdir=workdir, demux=True)
        if result.exit_code:
            stdout, stderr = result.output or (b"", b"")
            raise RuntimeError(f"Container command failed ({result.exit_code}): {(stdout + stderr).decode(errors='replace')}")

    def _prepare_kernel_tree(self, *, reset_tree: bool = True) -> None:
        self._run_root(["git", "config", "--system", "--add", "safe.directory", "*"])
        if not reset_tree:
            return
        self._run_root(["git", "reset", "--hard", self.commit_sha], workdir=self._git_workdir)
        self._run_root(["git", "clean", "-fdx"], workdir=self._git_workdir)
        self._run_root(["chown", "-R", "patchwise:patchwise", self._git_workdir])

    def _configure_git_identity(self) -> None:
        for key, value in (("user.name", _GIT_COMMITTER["name"]), ("user.email", _GIT_COMMITTER["email"])):
            self._run_root(["git", "config", "--system", key, value])

    def _fix_build_directory_permissions(self) -> None:
        if not self.commit_sha:
            return
        directory = str(self.build_dir / self.commit_sha)
        self._run_root(["mkdir", "-p", directory])
        self._run_root(["chown", "-R", "patchwise:patchwise", directory])
        self._run_root(["chmod", "-R", "755", directory])


CONTAINERS_BUILT: dict[str, DockerManager] = {}
