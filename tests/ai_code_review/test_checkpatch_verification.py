# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Exercise real Git state through the verification tool, without Docker or AI.

The analyzer boundary captures the complete patch it receives and reports
trailing whitespace in added lines. Git commands run unchanged in a disposable
repository, so these tests distinguish original commits from staged, unstaged,
and amended candidates rather than asserting a particular shell implementation.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from git import Actor, Repo

from patchwise.docker import DockerExecResult
from patchwise.patch_review.ai_agent.agent import Agent

ACTOR = Actor("Test Author", "test@example.invalid")
ANALYZER = """#!{python}
import os
import sys
from pathlib import Path

patch = sys.stdin.read()
Path(os.environ['CHECKPATCH_TEST_CAPTURE']).write_text(patch)
errors = sum(line.startswith('+') and line.endswith(' ') for line in patch.splitlines())
if errors:
    print('ERROR: trailing whitespace')
print(f'total: {{errors}} errors, 0 warnings, 4 lines checked')
sys.exit(1 if errors else 0)
"""


class LocalDocker:
    def __init__(self, repo, sha, capture):
        self._git_workdir = repo.working_tree_dir
        self.commit_sha = sha
        self.capture = capture

    def exec_command(self, command, cwd=None, *, input=None):
        env = dict(os.environ, CHECKPATCH_TEST_CAPTURE=str(self.capture))
        payload = input.encode("utf-8") if isinstance(input, str) else input
        result = subprocess.run(
            command,
            cwd=cwd or self._git_workdir,
            input=payload,
            stdin=subprocess.DEVNULL if payload is None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        return DockerExecResult(result.returncode, result.stdout, result.stderr)


def make_repo(tmp_path, root=False):
    repo = Repo.init(tmp_path / "repo")
    with repo.config_writer() as config:
        config.set_value("user", "name", ACTOR.name)
        config.set_value("user", "email", ACTOR.email)
    script = Path(repo.working_tree_dir) / "scripts/checkpatch.pl"
    script.parent.mkdir()
    script.write_text(ANALYZER.format(python=sys.executable))
    script.chmod(0o755)
    source = Path(repo.working_tree_dir) / "drivers/probe.c"
    source.parent.mkdir()
    source.write_text("int value = 0;\n")
    if not root:
        repo.index.add(["scripts/checkpatch.pl", "drivers/probe.c"])
        repo.index.commit("Initial tree", author=ACTOR, committer=ACTOR)
    source.write_text("int value = 1; \n")
    repo.index.add(["scripts/checkpatch.pl", "drivers/probe.c"])
    original = repo.index.commit(
        "driver: Add board value\n\nAdd a board value.\n\n"
        "Signed-off-by: Test Author <test@example.invalid>",
        author=ACTOR,
        committer=ACTOR,
    )
    return repo, original, source


def make_agent(repo, commit, tmp_path, editing=True):
    agent = object.__new__(Agent)
    agent.logger = logging.getLogger("test.checkpatch-verification")
    agent.enable_edit_tools = editing
    agent.docker_manager = LocalDocker(repo, commit.hexsha, tmp_path / "captured.patch")
    return agent


@pytest.mark.parametrize("state", ["unstaged", "staged", "both", "amended"])
def test_verification_checks_current_candidate_and_preserves_index(tmp_path, state):
    repo, original, source = make_repo(tmp_path)
    agent = make_agent(repo, original, tmp_path)
    before = agent._tool_run_checkpatch()
    assert before["ok"] and "Issues remain" in before["result"]
    source.write_text("int value = 2;\n")
    if state in {"staged", "both", "amended"}:
        repo.index.add(["drivers/probe.c"])
    if state == "both":
        source.write_text("int value = 3;\n")
    if state == "amended":
        repo.index.commit(
            "driver: Correct board value\n\nUse a corrected value.\n\n"
            "Signed-off-by: Test Author <test@example.invalid>",
            author=ACTOR,
            committer=ACTOR,
            parent_commits=original.parents,
        )
    index_before = Path(repo.index.path).read_bytes()
    head_before = repo.head.commit.hexsha
    content_before = source.read_bytes()

    result = agent._tool_run_checkpatch()

    assert result["ok"] and "SUCCESS" in result["result"]
    candidate = agent.docker_manager.capture.read_text()
    assert "+int value = 1; " not in candidate
    assert f"+int value = {3 if state == 'both' else 2};\n" in candidate
    assert "-int value = 0;" in candidate
    if state == "amended":
        assert "driver: Correct board value" in candidate
        assert "Use a corrected value." in candidate
    assert Path(repo.index.path).read_bytes() == index_before
    assert repo.head.commit.hexsha == head_before
    assert source.read_bytes() == content_before


def test_candidate_uses_reviewed_parent_not_current_head_parent(tmp_path):
    repo, original, source = make_repo(tmp_path)
    source.write_text("int value = 2;\nint later_value = 3;\n")
    repo.index.add(["drivers/probe.c"])
    repo.index.commit(
        "driver: Update candidate\n\nKeep both board values.\n\n"
        "Signed-off-by: Test Author <test@example.invalid>",
        author=ACTOR,
        committer=ACTOR,
    )
    agent = make_agent(repo, original, tmp_path)

    result = agent._tool_run_checkpatch()

    assert result["ok"]
    candidate = agent.docker_manager.capture.read_text()
    assert "-int value = 0;" in candidate
    assert "+int value = 2;" in candidate
    assert "+int later_value = 3;" in candidate
    assert "driver: Update candidate" in candidate


def test_root_commit_candidate_is_compared_with_empty_tree(tmp_path):
    repo, original, source = make_repo(tmp_path, root=True)
    source.write_text("int value = 2;\n")
    agent = make_agent(repo, original, tmp_path)

    result = agent._tool_run_checkpatch()

    assert result["ok"] and "SUCCESS" in result["result"]
    candidate = agent.docker_manager.capture.read_text()
    assert "+int value = 2;" in candidate
    assert "--- /dev/null" in candidate


def test_read_only_tool_keeps_original_commit_even_with_newer_head(tmp_path):
    repo, original, source = make_repo(tmp_path)
    source.write_text("int later_only = 2;\n")
    repo.index.add(["drivers/probe.c"])
    repo.index.commit("Later unrelated commit", author=ACTOR, committer=ACTOR)
    source.write_text("int dirty_only = 3;\n")
    agent = make_agent(repo, original, tmp_path, editing=False)

    result = agent._tool_run_checkpatch()

    assert result["ok"] and "Issues remain" in result["result"]
    candidate = agent.docker_manager.capture.read_text()
    assert "+int value = 1; " in candidate
    assert "later_only" not in candidate
    assert "dirty_only" not in candidate
    assert "driver: Add board value" in candidate


@pytest.mark.parametrize("editing", [False, True], ids=["read-only", "editing"])
def test_git_failure_cannot_be_reported_as_success(tmp_path, editing):
    repo, original, _ = make_repo(tmp_path)
    agent = make_agent(repo, original, tmp_path, editing)
    agent.docker_manager.commit_sha = "f" * 40

    result = agent._tool_run_checkpatch()

    assert result["ok"] is False
    assert "SUCCESS" not in result.get("result", "")
    assert not agent.docker_manager.capture.exists()


def test_analyzer_failure_is_returned_as_tool_error(tmp_path):
    repo, original, _ = make_repo(tmp_path)
    agent = make_agent(repo, original, tmp_path)
    script = Path(repo.working_tree_dir) / "scripts/checkpatch.pl"
    script.write_text(
        f"#!{sys.executable}\nimport sys\nprint('analyzer failed', file=sys.stderr)\nsys.exit(2)\n"
    )

    result = agent._tool_run_checkpatch()

    assert result["ok"] is False
    assert "analyzer failed" in result["error"]


def test_empty_failed_analyzer_cannot_claim_no_diagnostics(tmp_path):
    repo, original, _ = make_repo(tmp_path)
    agent = make_agent(repo, original, tmp_path)
    script = Path(repo.working_tree_dir) / "scripts/checkpatch.pl"
    script.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(1)\n")

    result = agent._tool_run_checkpatch()

    assert result["ok"] is False
