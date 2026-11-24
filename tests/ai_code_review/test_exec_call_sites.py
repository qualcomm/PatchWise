# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import io
from pathlib import Path
import tarfile
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from patchwise.docker import DockerExecResult, DockerManager
from patchwise.patch_review.ai_agent.agent import Agent
from patchwise.patch_review.ai_fix.ai_fix import AiFix
from patchwise.patch_review.ai_fix.checkpatch_fixer import CheckpatchFixer
from patchwise.patch_review.ai_fix.sparse_fixer import SparseFixer
from patchwise.patch_review.ai_review.ts_indexer import TsIndex
from patchwise.patch_review.static_analysis.static_analysis import StaticAnalysis


@pytest.fixture
def manager():
    manager = Mock(spec=DockerManager)
    manager.kernel_dir = Path("/home/patchwise/kernel")
    manager.sandbox_path = Path("/home/patchwise")
    manager.build_dir = Path("/home/patchwise/build")
    manager.git_subdir = ""
    manager._git_workdir = str(manager.kernel_dir)
    manager.commit_sha = "abcdef"
    return manager


@pytest.fixture
def index(manager):
    return TsIndex(manager, Mock(), [])


def test_hash_files_supplies_text_input_and_decodes_hashes(index, manager):
    manager.exec_command.return_value = DockerExecResult(0, b"sha1\nsha2\n", b"")
    assert index._hash_files(["a.c", "目录/b.c"]) == {"a.c": "sha1", "目录/b.c": "sha2"}
    manager.exec_command.assert_called_once_with(
        ["git", "hash-object", "--no-filters", "--stdin-paths"],
        cwd=str(manager.kernel_dir),
        input="a.c\n目录/b.c\n",
    )


@pytest.mark.parametrize(
    "exit_code,stdout", [(1, b""), (0, b"sha1\n"), (0, b"sha1\nsha2\nextra\n")]
)
def test_hash_files_reports_failure_or_wrong_hash_count(
    index, manager, exit_code, stdout
):
    manager.exec_command.return_value = DockerExecResult(
        exit_code, stdout, b"hash diagnostic"
    )
    with pytest.raises(RuntimeError, match="git hash-object failed: hash diagnostic"):
        index._hash_files(["a.c", "b.c"])


@pytest.mark.parametrize("method", ["_hash_files", "_read_files"])
def test_index_empty_paths_do_not_execute(index, manager, method):
    assert getattr(index, method)([]) == {}
    manager.exec_command.assert_not_called()


def test_read_files_supplies_nul_separated_bytes_and_preserves_tar_contents(
    index, manager
):
    contents = {"a.c": b"\x00\xff", "目录/b.c": "日本語".encode()}
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        directory = tarfile.TarInfo("目录")
        directory.type = tarfile.DIRTYPE
        tar.addfile(directory)
        for name, data in contents.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    manager.exec_command.return_value = DockerExecResult(0, archive.getvalue(), b"")

    assert index._read_files(["a.c", "目录/b.c", "a.c"]) == contents
    manager.exec_command.assert_called_once_with(
        ["tar", "-cf", "-", "--null", "-T", "-"],
        cwd=str(manager.kernel_dir),
        input=b"a.c\0" + "目录/b.c".encode(),
    )


def test_read_files_reports_binary_stderr_on_failure(index, manager):
    manager.exec_command.return_value = DockerExecResult(2, b"", b"tar diagnostic\xff")
    with pytest.raises(RuntimeError, match="tar of 1 files failed") as exc:
        index._read_files(["a.c"])
    assert repr(b"tar diagnostic\xff") in str(exc.value)


def test_index_lookup_decodes_candidates(index, manager):
    # One exec runs rg and git hash-object: rg output, NUL, files, NUL, SHAs.
    path = str(manager.kernel_dir / "目录/a.c").encode()
    sha = "a" * 40
    manager.exec_command.return_value = DockerExecResult(
        0, path + b"\n\0" + path + b"\n\0" + sha.encode() + b"\n", b""
    )
    index._constructs_for_paths = Mock(return_value={})
    assert index.lookup("function") == []
    index._constructs_for_paths.assert_called_once_with({"目录/a.c": sha})


@pytest.fixture
def agent(manager):
    agent = object.__new__(Agent)
    agent.docker_manager = manager
    agent.enable_edit_tools = False
    agent.logger = Mock()
    agent._log_tool_call = Mock()
    return agent


@pytest.mark.parametrize("exit_code", [0, 1, 124, 137])
def test_bash_preserves_command_deadline_output_and_exit_status(
    agent, manager, exit_code
):
    manager.exec_command.return_value = DockerExecResult(
        exit_code, "中文".encode(), b"stderr"
    )
    result = agent._run_bash("echo test", None, 3)

    manager.exec_command.assert_called_once_with(
        ["timeout", "-k", "5", "3", "sh", "-c", "echo test"],
        cwd=str(manager.kernel_dir),
        wait_timeout=18,
    )
    assert result["ok"] is (exit_code == 0)
    assert result["exit_code"] == exit_code
    assert result["result"].startswith("中文stderr")
    assert result["timed_out"] is (exit_code in (124, 137))
    assert result["truncated"] is False


def test_bash_truncates_output_before_adding_timeout_notice(agent, manager):
    agent._BASH_OUTPUT_CAP = 5
    manager.exec_command.return_value = DockerExecResult(124, b"123456", b"stderr")
    result = agent._run_bash("sleep 10", None, 1)
    assert result["truncated"] is True
    assert result["result"].startswith("12345\n[timed out after 1s")


def test_bash_client_wait_failure_is_reported_without_kill_or_retry(agent, manager):
    manager.exec_command.side_effect = TimeoutError(
        "Docker exec did not finish responding; command was not cancelled"
    )
    result = agent.dispatch_tool("bash_timeout", {"command": "sleep 10", "timeout": 1})
    assert result["ok"] is False
    assert "command was not cancelled" in result["error"]
    assert "timed_out" not in result
    manager.exec_command.assert_called_once()


@pytest.mark.parametrize("exit_code", [0, 1])
def test_agent_validates_paths_using_exit_status(agent, manager, exit_code):
    agent._abs_in_kernel = Mock()
    agent._kernel_rel = Mock(return_value="a.c")
    agent._container_kernel_path = Mock(return_value="/kernel/a.c")
    manager.exec_command.return_value = DockerExecResult(exit_code, b"", b"")
    if exit_code:
        with pytest.raises(ValueError, match="path not found"):
            agent._validate_existing_kernel_path("a.c")
    else:
        assert agent._validate_existing_kernel_path("a.c") == "a.c"
    manager.exec_command.assert_called_once_with(
        ["test", "-e", "/kernel/a.c"], cwd=None
    )


def test_agent_sparse_combines_decoded_diagnostics(agent, manager):
    manager.exec_command.side_effect = [
        DockerExecResult(0, b"a.c\n", b""),
        DockerExecResult(2, b"out\xff", b"err\xff"),
    ]
    result = agent._tool_run_sparse()
    assert result["ok"] is False
    assert "make exited with code 2" in result["error"]
    assert "out\ufffderr\ufffd" in result["error"]


def test_agent_checkpatch_decodes_output(agent, manager):
    manager.exec_command.side_effect = [
        DockerExecResult(0, b"", b""),
        DockerExecResult(0, b"patch\n", b""),
        DockerExecResult(1, b"warning: issue\xff", b""),
    ]
    result = agent._tool_run_checkpatch()
    assert result["ok"] is True
    assert "warning: issue\ufffd" in result["result"]


def test_agent_diff_files_decode_and_include_git_subdir(agent, manager):
    manager.git_subdir = "common"
    manager.exec_command.return_value = DockerExecResult(
        0, "目录/a.c\nb.c\n".encode(), b""
    )
    assert agent._files_in_diff() == {"common/目录/a.c", "common/b.c"}


@pytest.fixture
def fixer(manager):
    fixer = object.__new__(AiFix)
    fixer.patch_review = SimpleNamespace(docker_manager=manager)
    fixer.logger = Mock()
    return fixer


def test_generate_git_patch_decodes_output_and_supplies_commit_message(fixer, manager):
    manager.exec_command.side_effect = [
        DockerExecResult(1, b"", b""),
        DockerExecResult(0, "Subject 中文\n\nSigned-off-by: Someone\n".encode(), b""),
        DockerExecResult(0, b"", b""),
        DockerExecResult(0, b"patch\xff\n", b""),
    ]
    assert fixer._generate_git_patch() == "patch\ufffd"
    assert manager.exec_command.call_args_list[2] == call(
        ["git", "commit", "-a", "--amend", "-F", "-"],
        cwd=str(manager.kernel_dir),
        input="Subject 中文\n",
    )


def test_generate_git_patch_no_changes_does_not_amend(fixer, manager):
    manager.exec_command.return_value = DockerExecResult(0, b"", b"")
    assert fixer._generate_git_patch() == ""
    manager.exec_command.assert_called_once()


@pytest.mark.parametrize(
    "stage,message",
    [
        (1, "git log failed"),
        (2, "git commit --amend failed"),
        (3, "git format-patch failed"),
    ],
)
def test_generate_git_patch_reports_decoded_errors(fixer, manager, stage, message):
    results = [
        DockerExecResult(1, b"", b""),
        DockerExecResult(0, b"message", b""),
        DockerExecResult(0, b"", b""),
        DockerExecResult(0, b"patch", b""),
    ]
    results[stage] = DockerExecResult(2, b"", b"diagnostic\xff")
    manager.exec_command.side_effect = results
    with pytest.raises(RuntimeError, match=message) as exc:
        fixer._generate_git_patch()
    assert "diagnostic\ufffd" in str(exc.value)


@pytest.mark.parametrize("exit_code", [0, 1])
def test_checkpatch_restore_trailers_supplies_text_and_checks_status(
    manager, exit_code
):
    fixer = object.__new__(CheckpatchFixer)
    fixer.patch_review = SimpleNamespace(docker_manager=manager)
    fixer.logger = Mock()
    manager.exec_command.side_effect = [
        DockerExecResult(0, "Subject 中文\n\n".encode(), b""),
        DockerExecResult(exit_code, b"", b"diagnostic\xff"),
    ]
    fixer._restore_trailers_if_missing(["Signed-off-by: Someone"])
    assert manager.exec_command.call_args_list[1] == call(
        ["git", "commit", "--amend", "-F", "-"],
        cwd=str(manager.kernel_dir),
        input="Subject 中文\nSigned-off-by: Someone\n",
    )
    if exit_code:
        assert "diagnostic\ufffd" in fixer.logger.warning.call_args.args[0]
    else:
        fixer.logger.warning.assert_not_called()


@pytest.mark.parametrize("cls", [CheckpatchFixer, SparseFixer])
def test_script_fixer_stops_on_failed_file_list(manager, cls):
    fixer = object.__new__(cls)
    fixer.patch_review = SimpleNamespace(docker_manager=manager)
    fixer.logger = Mock()
    manager.exec_command.return_value = DockerExecResult(2, b"", b"error")
    assert fixer._apply_script_fixes() is False
    manager.exec_command.assert_called_once_with(
        ["git", "diff", "--name-only", "HEAD~1"], cwd=str(manager.kernel_dir)
    )


def test_static_analysis_reset_executes_immediately(manager):
    manager.exec_command.return_value = DockerExecResult(0, b"", b"")
    review = SimpleNamespace(docker_manager=manager, logger=Mock())
    StaticAnalysis.reset_tree(review, SimpleNamespace(hexsha="abcdef"))
    manager.exec_command.assert_called_once_with(
        ["git", "reset", "--hard", "abcdef"], cwd=str(manager.kernel_dir)
    )


def test_static_analysis_reset_reports_failure(manager):
    manager.exec_command.return_value = DockerExecResult(
        128, b"", b"invalid revision\xff"
    )
    review = SimpleNamespace(docker_manager=manager, logger=Mock())
    with pytest.raises(RuntimeError, match="git reset failed: invalid revision\ufffd"):
        StaticAnalysis.reset_tree(review, SimpleNamespace(hexsha="bad"))
