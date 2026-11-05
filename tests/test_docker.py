import subprocess
import threading
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from docker.errors import DockerException, NotFound

from patchwise.docker import DockerExecProcess, DockerManager, check_docker_available


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ((b"stdout", None), ("stdout", "")),
        ((None, b"stderr"), ("", "stderr")),
        (None, ("", "")),
    ],
)
def test_exec_decodes_empty_demuxed_streams(output, expected):
    """Docker's SDK represents an empty demuxed stream as None."""
    manager = object.__new__(DockerManager)
    container = Mock()
    container.exec_run.return_value = SimpleNamespace(output=output, exit_code=0)
    manager._container = Mock(return_value=container)

    exit_code, streams = manager._exec(
        ["echo", "test"],
        "/tmp",
        input=None,
        text=True,
        user=None,
        environment=None,
    )

    assert exit_code == 0
    assert streams == expected


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("/container/path", {"host": {"bind": "/container/path", "mode": "rw"}}),
        ("/container/path:ro", {"host": {"bind": "/container/path", "mode": "ro"}}),
    ],
)
def test_mount_preserves_destination_mode(target, expected):
    assert DockerManager._mount("host", target) == expected


def test_exec_process_honors_host_timeout_then_returns_result():
    manager = Mock()
    manager.logger = Mock()
    started = threading.Event()
    release = threading.Event()

    def execute(*_args, **_kwargs):
        started.set()
        release.wait()
        return 0, ("done", "")

    manager._exec.side_effect = execute
    process = DockerExecProcess(manager, ["sleep", "1"], "/tmp")

    with pytest.raises(subprocess.TimeoutExpired):
        process.communicate(timeout=0.01)
    assert started.wait(1)

    release.set()
    assert process.communicate() == ("done", "")
    assert process.returncode == 0


def test_exec_process_kill_warns_that_docker_exec_cannot_be_stopped():
    manager = Mock()
    manager.logger = Mock()
    process = DockerExecProcess(manager, ["sleep", "1"], "/tmp")

    with pytest.deprecated_call(match="cannot stop an individual Docker exec"):
        process.kill()

    manager.logger.warning.assert_called_once()


def test_exec_process_rejects_stdin_after_execution_has_started():
    manager = Mock()
    manager._exec.return_value = (0, ("", ""))
    process = DockerExecProcess(manager, ["true"], "/tmp")

    assert process.communicate() == ("", "")
    with pytest.raises(ValueError, match="first communicate"):
        process.communicate(input="more")


def test_overlay_setup_cleans_partial_volumes_on_failure():
    manager = object.__new__(DockerManager)
    manager.client = Mock()
    manager.logger = Mock()
    manager.container_name = "review"
    manager.repo_path = "/repo"
    manager._remove_volume = Mock()
    manager.client.containers.run.side_effect = DockerException("helper failed")

    with pytest.raises(DockerException, match="helper failed"):
        manager._setup_kernel_overlay()

    assert manager._remove_volume.call_args_list[-2:] == [
        call("patchwise-kernel-review"),
        call("patchwise-kernel-backing-review"),
    ]


def test_build_error_includes_image_and_daemon_detail():
    manager = object.__new__(DockerManager)
    manager.client = Mock()
    manager.logger = Mock()
    manager.client.images.build.side_effect = DockerException("daemon unavailable")

    with pytest.raises(
        RuntimeError, match="Failed to build image patchwise-base:latest: daemon unavailable"
    ):
        manager._build("Dockerfile", "patchwise-base:latest")


def test_start_container_cleans_container_and_overlay_after_preparation_failure():
    manager = object.__new__(DockerManager)
    manager.client = Mock()
    manager.logger = Mock()
    manager.container_name = "review"
    manager.image_tag = "image"
    manager.kernel_dir = "/kernel"
    manager._kernel_overlay_volume = None
    manager._setup_kernel_overlay = Mock(return_value="overlay")
    manager._container = Mock(return_value=Mock())
    manager._configure_git_identity = Mock()
    manager._prepare_kernel_tree = Mock(side_effect=RuntimeError("git failed"))
    manager._cleanup_kernel_overlay = Mock()

    with pytest.raises(RuntimeError, match="git failed"):
        manager._start_container({}, reset_tree=True)

    manager._container.return_value.remove.assert_called_with(force=True)
    manager._cleanup_kernel_overlay.assert_called_once()


def test_ts_cache_restarts_existing_stopped_container(monkeypatch):
    client = Mock()
    container = Mock(status="exited")
    client.containers.get.return_value = container
    monkeypatch.setattr("patchwise.docker.docker.from_env", lambda: client)
    monkeypatch.setattr(DockerManager, "_wait_ts_cache_ready", Mock())
    monkeypatch.setattr(DockerManager, "ts_cache_initialized", False)

    DockerManager.ensure_ts_cache_service()

    container.reload.assert_called_once()
    container.start.assert_called_once()
    DockerManager._wait_ts_cache_ready.assert_called_once_with(container)


def test_ts_cache_creates_container_when_absent(monkeypatch):
    client = Mock()
    client.containers.get.side_effect = NotFound("missing")
    container = Mock()
    client.containers.run.return_value = container
    monkeypatch.setattr("patchwise.docker.docker.from_env", lambda: client)
    monkeypatch.setattr("patchwise.docker.redis_address", lambda: ("127.0.0.1", 6380))
    monkeypatch.setattr(DockerManager, "_wait_ts_cache_ready", Mock())
    monkeypatch.setattr(DockerManager, "ts_cache_initialized", False)

    DockerManager.ensure_ts_cache_service()

    assert client.containers.run.call_args.kwargs["ports"] == {"6379/tcp": ("127.0.0.1", 6380)}
    DockerManager._wait_ts_cache_ready.assert_called_once_with(container)


def test_run_cmd_with_timer_updates_terminal_until_command_finishes(monkeypatch):
    manager = object.__new__(DockerManager)
    manager.logger = Mock()
    manager.logger.isEnabledFor.return_value = True
    process = Mock()
    process.communicate.side_effect = [subprocess.TimeoutExpired(["make"], 5), ("out", "err")]
    manager.run_command = Mock(return_value=process)
    monkeypatch.setattr("patchwise.ui.events.has_subscribers", lambda: False)
    writes = []
    monkeypatch.setattr("patchwise.docker.sys.stdout.write", writes.append)
    monkeypatch.setattr("patchwise.docker.sys.stdout.flush", lambda: None)
    monkeypatch.setattr("patchwise.docker.time.time", lambda: 10)

    assert manager.run_cmd_with_timer(["make"], "Building") == "outerr"
    assert any("Building... 0s elapsed" in write for write in writes)


def test_check_docker_available_reports_missing_docker(monkeypatch):
    """A missing Docker socket should direct users to Docker installation help."""
    error = DockerException("Error while fetching server API version")
    error.__cause__ = FileNotFoundError("No such file or directory")
    client = Mock()
    client.ping.side_effect = error
    monkeypatch.setattr("patchwise.docker.docker.from_env", lambda: client)

    with pytest.raises(
        SystemExit, match="Docker is not installed or the Docker socket is unavailable"
    ) as exc:
        check_docker_available()

    assert "https://docs.docker.com/engine/install/" in str(exc.value)


def test_check_docker_available_reports_daemon_error(monkeypatch):
    """Unexpected daemon failures retain their useful SDK error detail."""
    client = Mock()
    client.ping.side_effect = DockerException("daemon is not running")
    monkeypatch.setattr("patchwise.docker.docker.from_env", lambda: client)

    with pytest.raises(SystemExit, match="Unable to reach the Docker daemon") as exc:
        check_docker_available()

    assert "daemon is not running" in str(exc.value)


def test_check_docker_available_reports_permission_error(monkeypatch):
    """Permission failures should tell users how to grant Docker access."""
    client = Mock()
    client.ping.side_effect = DockerException("permission denied while connecting")
    monkeypatch.setattr("patchwise.docker.docker.from_env", lambda: client)

    with pytest.raises(SystemExit, match="Add your user to the 'docker' group"):
        check_docker_available()
