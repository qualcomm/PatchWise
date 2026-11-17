# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from dataclasses import FrozenInstanceError
import socket
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from docker.errors import DockerException

from patchwise.docker import DockerExecResult, DockerManager


@pytest.mark.parametrize("field", ["stdout", "stderr"])
def test_exec_result_decodes_unicode_without_changing_bytes(field):
    text = "中文 日本語 العربية"
    raw = text.encode("utf-8")
    result = DockerExecResult(7, raw, raw)

    assert getattr(result, f"{field}_text")() == text
    assert getattr(result, field) == raw
    assert result.exit_code == 7
    with pytest.raises(FrozenInstanceError):
        result.exit_code = 0


@pytest.mark.parametrize("field", ["stdout", "stderr"])
def test_exec_result_encoding_and_error_overrides(field):
    raw = "日本語".encode("shift_jis")
    result = DockerExecResult(0, raw, raw)
    decode = getattr(result, f"{field}_text")

    assert decode(encoding="shift_jis") == "日本語"
    assert decode() == raw.decode("utf-8", errors="replace")
    assert decode(errors="ignore") == raw.decode("utf-8", errors="ignore")
    with pytest.raises(UnicodeDecodeError):
        decode(errors="strict")
    with pytest.raises(LookupError):
        decode(encoding="not-an-encoding")
    assert getattr(result, field) == raw


def test_exec_result_empty_streams():
    result = DockerExecResult(0, b"", b"")
    assert result.stdout_text() == result.stderr_text() == ""


@pytest.fixture
def manager():
    manager = object.__new__(DockerManager)
    manager.logger = Mock()
    return manager


@pytest.mark.parametrize(
    "output", [(b"out\xff", None), (None, b"err\xff"), (None, None), None]
)
def test_exec_command_keeps_sdk_bytes_and_normalizes_empty_streams(manager, output):
    container = Mock()
    container.exec_run.return_value = SimpleNamespace(exit_code=9, output=output)
    manager._container = Mock(return_value=container)

    result = manager.exec_command(["test"], user="root", environment={"LANG": "C"})

    stdout, stderr = output or (None, None)
    assert result == DockerExecResult(9, stdout or b"", stderr or b"")
    container.exec_run.assert_called_once_with(
        ["test"],
        workdir=str(manager.sandbox_path),
        user="root",
        environment={"LANG": "C"},
        demux=True,
    )


@pytest.mark.parametrize("input", ["中文", b"\x00\xff", "", b""])
def test_exec_command_supplies_buffered_input_and_keeps_binary_output(manager, input):
    manager.client = Mock()
    manager._container = Mock(return_value=Mock(id="container-id"))
    manager.client.api.exec_create.return_value = {"Id": "exec-id"}
    manager.client.api.exec_inspect.return_value = {"ExitCode": 3}
    client_socket, daemon_socket = socket.socketpair()
    manager.client.api.exec_start.return_value = client_socket
    payload = input.encode("utf-8") if isinstance(input, str) else input
    raw = b"\x00\xff"
    daemon_socket.sendall(bytes([1, 0, 0, 0]) + len(raw).to_bytes(4, "big") + raw)
    daemon_socket.shutdown(socket.SHUT_WR)
    try:
        result = manager.exec_command(["cat"], cwd="/tmp", input=input)
        assert result == DockerExecResult(3, raw, b"")
        assert daemon_socket.recv(1024) == payload
        assert daemon_socket.recv(1) == b""
        assert client_socket.fileno() == -1
        manager.client.api.exec_create.assert_called_once_with(
            "container-id",
            ["cat"],
            stdin=True,
            stdout=True,
            stderr=True,
            workdir="/tmp",
            user=None,
            environment=None,
        )
    finally:
        daemon_socket.close()
        client_socket.close()


@pytest.mark.parametrize("wait_timeout", [None, 1])
@pytest.mark.parametrize(
    "error", [DockerException("disconnected"), TimeoutError("transport")]
)
def test_exec_command_preserves_execution_failures(manager, wait_timeout, error):
    manager._exec = Mock(side_effect=error)
    with pytest.raises(type(error)) as exc:
        manager.exec_command(["true"], wait_timeout=wait_timeout)
    assert exc.value is error


@pytest.mark.parametrize("repetitions", [1, 3])
def test_exec_command_wait_timeout_does_not_cancel_or_retry(manager, repetitions):
    release = threading.Event()
    started = [threading.Event() for _ in range(repetitions)]
    finished = [threading.Event() for _ in range(repetitions)]

    def execute(command, *_args, **_kwargs):
        index = int(command[1])
        started[index].set()
        try:
            release.wait()
            return 0, (b"done", b"")
        finally:
            finished[index].set()

    manager._exec = Mock(side_effect=execute)
    try:
        for index in range(repetitions):
            with pytest.raises(TimeoutError, match="command was not cancelled"):
                manager.exec_command(["command", str(index)], wait_timeout=0.01)
            assert started[index].wait(1)
            # The original worker remains alive; there is no cancellation or
            # second execution to retry or collect a fabricated result.
            assert not finished[index].is_set()
        assert manager._exec.call_count == repetitions
    finally:
        release.set()
        for event in finished:
            assert event.wait(1)


def test_exec_command_returns_result_with_bounded_wait(manager):
    manager._exec = Mock(return_value=(0, (b"done", b"")))
    assert manager.exec_command(["true"], wait_timeout=1) == DockerExecResult(
        0, b"done", b""
    )


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_exec_command_rejects_invalid_wait_timeout(manager, timeout):
    manager._exec = Mock()
    with pytest.raises(ValueError, match="finite and positive"):
        manager.exec_command(["true"], wait_timeout=timeout)
    manager._exec.assert_not_called()


def test_exec_command_rejects_non_buffered_input(manager):
    manager._exec = Mock()
    with pytest.raises(TypeError, match="str or bytes"):
        manager.exec_command(["cat"], input=object())
    manager._exec.assert_not_called()


@pytest.mark.parametrize("subscribers,info", [(True, True), (False, False)])
def test_timer_does_not_write_when_dashboard_or_log_level_suppresses_it(
    manager, monkeypatch, subscribers, info
):
    manager.logger.isEnabledFor.return_value = info
    manager.exec_command = Mock(return_value=DockerExecResult(0, b"", b"diagnostic"))
    monkeypatch.setattr("patchwise.ui.events.has_subscribers", lambda: subscribers)
    write = Mock()
    thread = Mock()
    monkeypatch.setattr("patchwise.docker.sys.stdout.write", write)
    monkeypatch.setattr("patchwise.docker.threading.Thread", thread)

    assert manager.run_cmd_with_timer(["make"], "Building") == "diagnostic"
    write.assert_not_called()
    thread.assert_not_called()
    manager.logger.debug.assert_any_call("diagnostic")


def test_timer_is_stopped_and_terminal_cleared_on_execution_error(manager, monkeypatch):
    manager.logger.isEnabledFor.return_value = True
    manager.exec_command = Mock(side_effect=DockerException("disconnected"))
    monkeypatch.setattr("patchwise.ui.events.has_subscribers", lambda: False)
    complete = Mock()
    timer = Mock()
    write = Mock()
    monkeypatch.setattr("patchwise.docker.threading.Event", lambda: complete)
    monkeypatch.setattr("patchwise.docker.threading.Thread", Mock(return_value=timer))
    monkeypatch.setattr("patchwise.docker.sys.stdout.write", write)
    monkeypatch.setattr("patchwise.docker.sys.stdout.flush", Mock())

    with pytest.raises(DockerException, match="disconnected"):
        manager.run_cmd_with_timer(["make"], "Building")
    complete.set.assert_called_once()
    timer.join.assert_called_once()
    write.assert_called_once_with("\r\033[K")


@pytest.mark.parametrize("exit_code", [0, 1])
def test_file_helpers_use_execution_result(manager, exit_code):
    manager.exec_command = Mock(
        return_value=DockerExecResult(exit_code, b"content", b"error")
    )
    assert manager.read_file("/tmp/file") == ("content" if exit_code == 0 else False)
    manager.exec_command.assert_called_once_with(["cat", "/tmp/file"])
    manager.exec_command.reset_mock()
    assert manager.write_file("/tmp/file", "中文") is (exit_code == 0)
    manager.exec_command.assert_called_once_with(["tee", "/tmp/file"], input="中文")
