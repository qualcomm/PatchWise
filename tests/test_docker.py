from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from patchwise.docker import DockerManager


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
