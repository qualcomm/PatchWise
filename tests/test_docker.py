import io
import socket
import subprocess
import threading
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from docker.errors import DockerException, NotFound

from patchwise import PACKAGE_PATH
from patchwise.docker import DockerExecProcess, DockerManager, check_docker_available


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ((b"stdout", None), ("stdout", "")),
        ((None, b"stderr"), ("", "stderr")),
        ((None, None), ("", "")),
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


def test_exec_demuxes_interleaved_socket_frames_and_writes_stdin():
    manager = object.__new__(DockerManager)
    manager.client = Mock()
    container = Mock(id="container-id")
    manager._container = Mock(return_value=container)
    manager.client.api.exec_create.return_value = {"Id": "exec-id"}
    manager.client.api.exec_inspect.return_value = {"ExitCode": 0}
    client_socket, daemon_socket = socket.socketpair()
    manager.client.api.exec_start.return_value = client_socket

    def frame(stream, payload):
        return bytes([stream, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload

    daemon_socket.sendall(frame(1, b"out-") + frame(2, b"err") + frame(1, b"put"))
    daemon_socket.shutdown(socket.SHUT_WR)

    exit_code, streams = manager._exec(
        ["cat"], "/tmp", input="input", text=True, user=None, environment=None
    )

    assert exit_code == 0
    assert streams == ("out-put", "err")
    assert daemon_socket.recv(5) == b"input"
    daemon_socket.close()


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


def test_exec_process_rejects_input_when_stdin_was_not_requested():
    manager = Mock()
    process = DockerExecProcess(manager, ["true"], "/tmp")

    with pytest.raises(ValueError, match="stdin was not requested"):
        process.communicate(input="input")


def test_interactive_command_alias_warns_and_uses_buffered_stdin():
    manager = object.__new__(DockerManager)
    manager.run_stdin_command = Mock(return_value="process")

    with pytest.deprecated_call(match="run_interactive_command"):
        assert manager.run_interactive_command(["cat"], "/tmp") == "process"

    manager.run_stdin_command.assert_called_once_with(["cat"], "/tmp")


def test_exec_process_rejects_stdin_after_execution_has_started():
    manager = Mock()
    manager._exec.return_value = (0, ("", ""))
    process = DockerExecProcess(manager, ["true"], "/tmp")

    assert process.communicate() == ("", "")
    with pytest.raises(ValueError, match="first communicate"):
        process.communicate(input="more")


@pytest.mark.parametrize(
    "error",
    [NotFound("missing"), DockerException("unavailable"), OSError("disconnected")],
)
def test_overlay_cleanup_attempts_both_volumes_after_error(error):
    manager = object.__new__(DockerManager)
    manager.client = Mock()
    manager.logger = Mock()
    manager.container_name = "review"
    manager._kernel_overlay_volume = "overlay"
    manager.client.volumes.get.side_effect = [error, Mock()]

    manager._cleanup_kernel_overlay()

    assert manager.client.volumes.get.call_args_list == [
        call("patchwise-kernel-review"),
        call("patchwise-kernel-backing-review"),
    ]
    assert manager._kernel_overlay_volume is None


def test_overlay_setup_only_creates_volumes():
    manager = object.__new__(DockerManager)
    manager.client = Mock()
    manager.logger = Mock()
    manager.container_name = "review"
    manager.repo_path = "/repo"
    manager.client.volumes.get.return_value.attrs = {"Mountpoint": "/volumes/backing"}

    assert manager._setup_kernel_overlay() == "patchwise-kernel-review"

    manager.client.volumes.get.return_value.remove.assert_not_called()
    assert manager.client.volumes.create.call_args_list == [
        call("patchwise-kernel-backing-review"),
        call(
            "patchwise-kernel-review",
            driver="local",
            driver_opts={
                "type": "overlay",
                "o": "lowerdir=/repo,upperdir=/volumes/backing/upper,workdir=/volumes/backing/work,metacopy=on",
                "device": "overlay",
            },
        ),
    ]


def test_build_error_includes_image_and_daemon_detail(monkeypatch):
    manager = object.__new__(DockerManager)
    manager.logger = Mock()
    process = Mock(stdout=io.StringIO("daemon unavailable\n"))
    process.wait.return_value = 1
    popen = Mock()
    popen.return_value.__enter__ = Mock(return_value=process)
    popen.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("patchwise.docker.subprocess.Popen", popen)

    with pytest.raises(
        RuntimeError,
        match="(?s)Failed to build image patchwise-base:latest .*daemon unavailable",
    ):
        manager._build("Dockerfile", "patchwise-base:latest")


def test_build_streams_cli_logs_without_loading_sdk_credentials(monkeypatch):
    manager = object.__new__(DockerManager)
    manager.client = Mock()
    manager.logger = Mock()
    manager.client.api.build.side_effect = DockerException("broken credential helper")
    process = Mock(stdout=io.StringIO("step 1\ndone\n"))
    process.wait.return_value = 0
    popen = Mock()
    popen.return_value.__enter__ = Mock(return_value=process)
    popen.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("patchwise.docker.subprocess.Popen", popen)

    manager._build("Dockerfile", "patchwise-base:latest")

    popen.assert_called_once_with(
        [
            "docker",
            "build",
            "--rm=true",
            "--force-rm=true",
            "-f",
            "Dockerfile",
            "-t",
            "patchwise-base:latest",
            str(PACKAGE_PATH),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    manager.logger.debug.assert_has_calls([call("step 1"), call("done")])
    manager.client.api.build.assert_not_called()
    manager.client.images.get.assert_called_once_with("patchwise-base:latest")
    process.wait.assert_called_once()


def test_build_reports_missing_image_after_successful_cli_exit(monkeypatch):
    manager = object.__new__(DockerManager)
    manager.client = Mock()
    manager.logger = Mock()
    manager.client.images.get.side_effect = NotFound("image missing")
    process = Mock(stdout=io.StringIO("done\n"))
    process.wait.return_value = 0
    popen = Mock()
    popen.return_value.__enter__ = Mock(return_value=process)
    popen.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("patchwise.docker.subprocess.Popen", popen)

    with pytest.raises(RuntimeError, match="Failed to build image test: image missing"):
        manager._build("Dockerfile", "test")


def test_build_reports_missing_cli(monkeypatch):
    manager = object.__new__(DockerManager)
    monkeypatch.setattr(
        "patchwise.docker.subprocess.Popen", Mock(side_effect=FileNotFoundError())
    )

    with pytest.raises(RuntimeError, match="Docker CLI is required.*Install Docker"):
        manager._build("Dockerfile", "patchwise-base:latest")


@pytest.mark.parametrize("output", [(None, b"error"), (b"error", None)])
def test_run_root_handles_empty_demuxed_streams(output):
    manager = object.__new__(DockerManager)
    manager._container = Mock(
        return_value=Mock(
            exec_run=Mock(return_value=SimpleNamespace(exit_code=1, output=output))
        )
    )

    with pytest.raises(RuntimeError, match="error"):
        manager._run_root(["false"])


def test_start_container_cleans_container_and_overlay_after_preparation_failure():
    manager = object.__new__(DockerManager)
    manager.client = Mock()
    manager.logger = Mock()
    manager.container_name = "review"
    manager.image_tag = "image"
    manager.kernel_dir = "/kernel"
    manager._kernel_overlay_volume = None
    manager._container_object = None
    manager._setup_kernel_overlay = Mock(return_value="overlay")
    manager._container = Mock(return_value=Mock())
    manager._configure_git_identity = Mock()
    manager._prepare_kernel_tree = Mock(side_effect=RuntimeError("git failed"))
    manager._cleanup_kernel_overlay = Mock()

    with pytest.raises(RuntimeError, match="git failed"):
        manager._start_container({}, reset_tree=True)

    manager._container.return_value.remove.assert_called_with(force=True)
    assert manager._cleanup_kernel_overlay.call_count == 2
    assert manager._container_object is None


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

    assert client.containers.run.call_args.kwargs["ports"] == {
        "6379/tcp": ("127.0.0.1", 6380)
    }
    DockerManager._wait_ts_cache_ready.assert_called_once_with(container)


def test_run_cmd_with_timer_updates_terminal_until_command_finishes(monkeypatch):
    manager = object.__new__(DockerManager)
    manager.logger = Mock()
    manager.logger.isEnabledFor.return_value = True
    process = Mock()
    process.communicate.side_effect = [
        subprocess.TimeoutExpired(["make"], 5),
        ("out", "err"),
    ]
    manager.run_command = Mock(return_value=process)
    monkeypatch.setattr("patchwise.ui.events.has_subscribers", lambda: False)
    writes = []
    monkeypatch.setattr("patchwise.docker.sys.stdout.write", writes.append)
    monkeypatch.setattr("patchwise.docker.sys.stdout.flush", lambda: None)
    monkeypatch.setattr("patchwise.docker.time.time", lambda: 10)

    assert manager.run_cmd_with_timer(["make"], "Building") == "outerr"
    assert any("Building... 0s elapsed" in write for write in writes)
    manager.logger.debug.assert_any_call("out")


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


def test_container_lookup_is_cached():
    manager = object.__new__(DockerManager)
    manager.client = Mock()
    manager.container_name = "review"
    manager._container_object = None

    assert manager._container() is manager._container()

    manager.client.containers.get.assert_called_once_with("review")


@pytest.mark.parametrize(
    "error",
    [None, NotFound("missing"), DockerException("busy"), OSError("disconnected")],
)
def test_container_cleanup_invalidates_cached_object(error):
    manager = object.__new__(DockerManager)
    manager.client = Mock()
    manager.logger = Mock()
    manager.container_name = "review"
    container = Mock()
    container.remove.side_effect = error
    manager._container_object = container

    manager._cleanup_container()

    container.remove.assert_called_once_with(force=True)
    assert manager._container_object is None
    assert manager._container() is manager.client.containers.get.return_value


def test_start_container_removes_stale_resources_before_setup_and_caches_new_container():
    manager = object.__new__(DockerManager)
    manager.client = Mock()
    manager.logger = Mock()
    manager.container_name = "review"
    manager.image_tag = "image"
    manager._container_object = None
    manager._configure_git_identity = Mock()
    manager._prepare_kernel_tree = Mock()
    calls = Mock()
    calls.attach_mock(manager.client.containers.get, "get_container")
    calls.attach_mock(manager.client.volumes.get, "get_volume")
    manager._setup_kernel_overlay = Mock(return_value="overlay")
    calls.attach_mock(manager._setup_kernel_overlay, "setup")
    calls.attach_mock(manager.client.containers.run, "run")

    manager._start_container({}, reset_tree=True)

    assert calls.mock_calls[:6] == [
        call.get_container("review"),
        call.get_container().remove(force=True),
        call.get_volume("patchwise-kernel-review"),
        call.get_volume().remove(force=True),
        call.get_volume("patchwise-kernel-backing-review"),
        call.get_volume().remove(force=True),
    ]
    assert calls.mock_calls[6] == call.setup()
    assert manager._container() is manager.client.containers.run.return_value
    manager.client.containers.get.assert_called_once_with("review")


@pytest.mark.parametrize("stage", ["backing", "helper", "overlay"])
def test_start_container_cleans_partial_overlay_after_setup_failure(stage):
    manager = object.__new__(DockerManager)
    manager.client = Mock()
    manager.logger = Mock()
    manager.container_name = "review"
    manager.repo_path = "/repo"
    manager._container_object = None
    manager.client.containers.get.side_effect = NotFound("missing")
    manager.client.volumes.get.return_value.attrs = {"Mountpoint": "/backing"}
    error = DockerException("setup failed")
    if stage == "helper":
        manager.client.containers.run.side_effect = error
    else:
        manager.client.volumes.create.side_effect = (
            error if stage == "backing" else [Mock(), error]
        )

    with pytest.raises(
        RuntimeError, match="Failed to start container review: setup failed"
    ):
        manager._start_container({}, reset_tree=True)

    assert manager.client.volumes.get.call_args_list[-2:] == [
        call("patchwise-kernel-review"),
        call("patchwise-kernel-backing-review"),
    ]
    assert manager._container_object is None
    assert manager._kernel_overlay_volume is None


@pytest.mark.parametrize(
    "error", [DockerException("unavailable"), OSError("disconnected")]
)
def test_start_container_preserves_preparation_error_when_cleanup_fails(error):
    manager = object.__new__(DockerManager)
    manager.client = Mock()
    manager.logger = Mock()
    manager.container_name = "review"
    manager.image_tag = "image"
    manager._container_object = None
    manager.client.containers.get.side_effect = NotFound("missing")
    manager._setup_kernel_overlay = Mock(return_value="overlay")
    manager._configure_git_identity = Mock(side_effect=RuntimeError("git failed"))
    manager.client.containers.run.return_value.remove.side_effect = error
    manager.client.volumes.get.return_value.remove.side_effect = error

    with pytest.raises(RuntimeError, match="git failed"):
        manager._start_container({}, reset_tree=True)

    assert manager._container_object is None
    assert manager._kernel_overlay_volume is None


def test_start_container_cleans_resources_after_permission_failure():
    manager = object.__new__(DockerManager)
    manager._repo_managed = False
    manager._start_container = Mock()
    manager._fix_build_directory_permissions = Mock(
        side_effect=RuntimeError("chown failed")
    )
    manager._cleanup_container = Mock()
    manager._cleanup_kernel_overlay = Mock()

    with pytest.raises(RuntimeError, match="chown failed"):
        manager.start_container()

    manager._cleanup_container.assert_called_once()
    manager._cleanup_kernel_overlay.assert_called_once()


def test_stop_container_invalidates_cached_object():
    manager = object.__new__(DockerManager)
    manager.client = Mock()
    manager.logger = Mock()
    manager.container_name = "review"
    container = Mock()
    manager._container_object = container

    manager.stop_container()

    container.stop.assert_called_once()
    container.remove.assert_called_once()
    assert manager._container_object is None
