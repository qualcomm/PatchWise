from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from docker.errors import DockerException

from patchwise.docker import DockerManager, check_docker_available


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
