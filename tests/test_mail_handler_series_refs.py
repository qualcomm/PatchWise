from email.message import EmailMessage
from pathlib import Path
from typing import Optional

from git import Repo

from patchwise.mail_handler import handler
from patchwise.patch_review.ai_agent.agent import Agent


def _commit(repo: Repo, path: Path, content: str, message: str) -> str:
    path.write_text(content)
    repo.index.add([str(path)])
    return repo.index.commit(message).hexsha


def _message(message_id: str, subject: str = "[PATCH] test") -> EmailMessage:
    msg = EmailMessage()
    msg["Message-Id"] = message_id
    msg["Subject"] = subject
    msg.set_content("patch body")
    return msg


def test_patch_series_refs_are_recorded_and_cleared(tmp_path: Path) -> None:
    repo = Repo.init(tmp_path)
    repo.git.config("user.name", "Patchwise Test")
    repo.git.config("user.email", "patchwise-test@example.com")
    file_path = tmp_path / "file.txt"

    base = _commit(repo, file_path, "base\n", "base")
    first = _commit(repo, file_path, "one\n", "one")
    second = _commit(repo, file_path, "two\n", "two")

    handler.record_patch_series_ref(repo, 1, first)
    handler.record_patch_series_ref(repo, 2, second)
    repo.git.update_ref(f"{handler.PATCHWISE_SERIES_REF_PREFIX}/99", base)

    assert repo.git.rev_parse(f"{handler.PATCHWISE_SERIES_REF_PREFIX}/1") == first
    assert repo.git.rev_parse(f"{handler.PATCHWISE_SERIES_REF_PREFIX}/2") == second

    handler.clear_patch_series_refs(repo)

    assert not repo.git.for_each_ref(handler.PATCHWISE_SERIES_REF_PREFIX)


def test_test_patch_from_mail_stashes_each_applied_patch_ref(
    monkeypatch, tmp_path: Path
) -> None:
    repo = Repo.init(tmp_path)
    repo.git.config("user.name", "Patchwise Test")
    repo.git.config("user.email", "patchwise-test@example.com")
    file_path = tmp_path / "file.txt"

    base = _commit(repo, file_path, "base\n", "base")
    first = _commit(repo, file_path, "one\n", "one")
    second = _commit(repo, file_path, "two\n", "two")
    repo.git.update_ref(f"{handler.PATCHWISE_SERIES_REF_PREFIX}/99", base)

    current = _message("<patch-1@example.com>", "[PATCH 1/2] one")
    series = [
        current,
        _message("<patch-2@example.com>", "[PATCH 2/2] two"),
    ]
    applied = iter([first, second])
    reviewed: dict[str, str] = {}

    monkeypatch.setattr(handler, "prepare_kernel_tree", lambda: repo)
    monkeypatch.setattr(handler, "apply_patch_from_email", lambda _msg, _repo: next(applied))

    def fake_review_commit(
        _reviews: set[str],
        commit,
        _repo_path: str,
        additional_context: Optional[str] = "",
    ):
        reviewed["commit"] = commit.hexsha
        return None

    monkeypatch.setattr(handler, "review_commit", fake_review_commit)

    assert handler.test_patch_from_mail(current, series, None, {"AiCodeReview"}) is None

    assert reviewed["commit"] == first
    assert repo.git.rev_parse(f"{handler.PATCHWISE_SERIES_REF_PREFIX}/1") == first
    assert repo.git.rev_parse(f"{handler.PATCHWISE_SERIES_REF_PREFIX}/2") == second
    assert f"{handler.PATCHWISE_SERIES_REF_PREFIX}/99" not in repo.git.for_each_ref(
        "--format=%(refname)", handler.PATCHWISE_SERIES_REF_PREFIX
    )


def test_format_series_context_lists_git_refs() -> None:
    current = _message("<patch-2@example.com>", "[PATCH 2/2] two")
    context = handler.format_series_context(
        current,
        [
            _message("<patch-1@example.com>", "[PATCH 1/2] one"),
            current,
        ],
    )

    assert f"{handler.PATCHWISE_SERIES_REF_PREFIX}/1 [PATCH 1/2] one" in context
    assert (
        f"{handler.PATCHWISE_SERIES_REF_PREFIX}/2 [PATCH 2/2] two"
        " <-- current patch under review"
    ) in context


class _FakeProcess:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode

    def communicate(self):
        return self.stdout, self.stderr


class _FakeDockerManager:
    kernel_dir = Path("/kernel")
    _git_workdir = "/kernel"

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run_command(self, command: list[str], cwd: Optional[str]):
        self.commands.append(command)
        if command[:3] == ["git", "rev-parse", "--verify"]:
            return _FakeProcess("deadbeef\n")
        if command[:3] == ["git", "--no-pager", "log"]:
            return _FakeProcess(
                "abc\x1fAlice\x1f2026-08-26\x1fsubject\n"
            )
        if command[:3] == ["git", "--no-pager", "show"]:
            return _FakeProcess("commit deadbeef\n")
        return _FakeProcess(returncode=1)


def test_git_log_accepts_series_ref_path() -> None:
    agent = Agent.__new__(Agent)
    agent.docker_manager = _FakeDockerManager()
    agent._validate_git_path = lambda path: path
    agent._split_tree = lambda rel: ("", rel)

    result = agent._tool_git_log(path="refs/patchwise/series/2:drivers/foo.c")

    assert result["ok"]
    log_cmd = agent.docker_manager.commands[-1]
    assert "deadbeef" in log_cmd
    assert log_cmd[-2:] == ["--", "drivers/foo.c"]


def test_git_show_accepts_bare_series_ref_without_dir() -> None:
    agent = Agent.__new__(Agent)
    agent.docker_manager = _FakeDockerManager()

    result = agent._tool_git_show(rev="refs/patchwise/series/2")

    assert result["ok"]
    show_cmd = agent.docker_manager.commands[-1]
    assert "deadbeef" in show_cmd
