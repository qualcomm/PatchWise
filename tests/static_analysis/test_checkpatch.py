# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Checkpatch's default path stays offline; filtering is opt-in and fail-open."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from patchwise.patch_review.static_analysis import checkpatch as module
from patchwise.patch_review.static_analysis.checkpatch import Checkpatch
from patchwise.patch_review.static_analysis.checkpatch_filter import filter_options
from patchwise.utils import config

RAW = ":0: WARNING:TYPO_SPELLING: 'SoM' may be misspelled - perhaps 'Some'?\n\ntotal: 0 errors, 1 warnings, 0 checks, 5 lines checked\n"


@pytest.fixture
def review(monkeypatch, tmp_path):
    # Avoid Docker initialization; exercise the production run method with only
    # external boundaries (container command and model completion) replaced.
    item = object.__new__(Checkpatch)
    item.logger = logging.getLogger("test.checkpatch")
    item.commit = SimpleNamespace(hexsha="abc123", message="Support the SoM board")
    item.repo = SimpleNamespace(git=SimpleNamespace(show=Mock(return_value="+SoM")))
    item.docker_manager = SimpleNamespace(
        repo_path=tmp_path,
        kernel_dir=tmp_path,
        container_name="unused-test-container",
        run_cmd_with_timer=Mock(return_value=RAW),
    )
    monkeypatch.setattr(module, "SANDBOX_PATH", tmp_path)
    monkeypatch.setattr(module, "Agent", Mock())
    return item


def options(enabled=True, model=None):
    result = {"enabled": enabled}
    if model is not None:
        result["model"] = model
    return {"static_analysis": {"Checkpatch": {"ai_filter": result}}}


@pytest.mark.parametrize("cfg", [{}, options(False)])
def test_default_does_not_prepare_context_or_call_model(review, monkeypatch, cfg):
    monkeypatch.setattr(module, "parse_config", lambda: cfg)
    assert review.run() == RAW
    review.repo.git.show.assert_not_called()
    module.Agent.assert_not_called()


def test_shipped_default_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "USER_CONFIG_PATH", tmp_path / "missing")
    assert filter_options(config.parse_config()) == (False, None)


@pytest.mark.parametrize(
    "cfg", [options("false"), options(1), options(True, ""), {"static_analysis": []}]
)
def test_bad_config_retains_original(review, monkeypatch, cfg):
    monkeypatch.setattr(module, "parse_config", lambda: cfg)
    assert review.run() == RAW
    module.Agent.assert_not_called()


@pytest.mark.parametrize("override", [None, "anthropic/custom-model"])
def test_filter_reuses_client_and_preserves_classification(
    review, monkeypatch, override
):
    monkeypatch.setattr(module, "parse_config", lambda: options(model=override))
    module.Agent.model = "configured-default"
    module.Agent.return_value.completion_with_retry.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "decisions": [
                                {
                                    "id": "F1",
                                    "suppress": True,
                                    "reason": "SoM is a board abbreviation",
                                }
                            ]
                        }
                    )
                )
            )
        ]
    )
    assert review.run() == ""
    review.repo.git.show.assert_called_once_with("abc123", format="", root=True)
    kwargs = module.Agent.return_value.completion_with_retry.call_args.kwargs
    assert kwargs["model"] == (override or "configured-default")
    assert kwargs["stream"] is False
    assert "tools" not in kwargs
    payload = json.loads(kwargs["messages"][1]["content"])
    assert payload["commit_message"] == "Support the SoM board"
    assert payload["diff"] == "+SoM"
    assert payload["findings"][0]["id"] == "F1"
    assert module.Agent.model == "configured-default"
    assert (
        len(
            list(
                (module.SANDBOX_PATH / "checkpatch_filter" / "abc123").glob(
                    "run-*/raw.txt"
                )
            )
        )
        == 1
    )


def test_empty_output_never_calls_model(review, monkeypatch):
    review.docker_manager.run_cmd_with_timer.return_value = ""
    monkeypatch.setattr(module, "parse_config", lambda: options())
    assert review.run() == ""
    module.Agent.assert_not_called()


@pytest.mark.parametrize("where", ["diff", "agent", "completion"])
def test_filter_setup_failure_keeps_raw(review, monkeypatch, where):
    monkeypatch.setattr(module, "parse_config", lambda: options())
    if where == "diff":
        review.repo.git.show.side_effect = RuntimeError("git failed")
    elif where == "agent":
        module.Agent.side_effect = RuntimeError("cache unavailable")
    else:
        module.Agent.return_value.completion_with_retry.side_effect = RuntimeError(
            "provider failed"
        )
    assert review.run() == RAW


def test_real_checkpatch_report_parses():
    from pathlib import Path
    from patchwise.patch_review.static_analysis.checkpatch_filter import parse_report

    raw = (Path(__file__).parent / "fixtures" / "checkpatch-report.txt").read_text()
    report = parse_report(raw)
    assert report is not None
    assert len(report.findings) == 8
    assert report.render(set()) == raw


@pytest.mark.parametrize("root_commit", [True, False], ids=["root", "with-parent"])
def test_filter_uses_reviewed_git_commit_not_working_tree(
    review, monkeypatch, tmp_path, root_commit
):
    from git import Actor, Repo

    repo = Repo.init(tmp_path / "repo")
    actor = Actor("Test Author", "test@example.invalid")
    source = tmp_path / "repo" / "board.c"
    if not root_commit:
        source.write_text("/* Initial board */\n")
        repo.index.add(["board.c"])
        repo.index.commit("Initial board", author=actor, committer=actor)
    source.write_text("/* Support the SoM (System on Module) board */\n")
    repo.index.add(["board.c"])
    commit = repo.index.commit("Support the SoM board", author=actor, committer=actor)
    # A newer HEAD and dirty worktree must not leak into the reviewed context.
    source.write_text("/* Later unrelated commit */\n")
    repo.index.add(["board.c"])
    repo.index.commit("Later commit", author=actor, committer=actor)
    source.write_text("/* Uncommitted unrelated content */\n")
    review.repo = repo
    review.commit = commit
    monkeypatch.setattr(module, "parse_config", lambda: options())

    def complete(**kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        assert payload["commit_message"] == commit.message
        assert "+/* Support the SoM (System on Module) board */" in payload["diff"]
        assert "Later unrelated" not in payload["diff"]
        assert "Uncommitted" not in payload["diff"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "decisions": [
                                    {
                                        "id": "F1",
                                        "suppress": True,
                                        "reason": "SoM is expanded in this commit",
                                    }
                                ]
                            }
                        )
                    )
                )
            ]
        )

    module.Agent.return_value.completion_with_retry.side_effect = complete
    assert review.run() == ""
    module.Agent.return_value.completion_with_retry.assert_called_once()
    assert source.read_text() == "/* Uncommitted unrelated content */\n"


@pytest.mark.parametrize("override", [None, "openai/filter-model"])
def test_real_completion_inherits_provider_credentials_and_reasoning(
    review, monkeypatch, override
):
    from patchwise.patch_review.ai_agent import agent as agent_module

    real_agent = agent_module.Agent
    monkeypatch.setattr(module, "Agent", real_agent)
    monkeypatch.setattr(real_agent, "model", "openai/default-model")
    monkeypatch.setattr(real_agent, "api_base", "https://provider.invalid/v1")
    monkeypatch.setattr(real_agent, "api_key", "fake-test-key")
    monkeypatch.setattr(real_agent, "reasoning_effort", "low")

    def init_without_navigation(self, *args):
        self.model = real_agent.model
        self.logger = logging.getLogger("test.agent")
        self.time_waiting_for_ai_response = 0

    monkeypatch.setattr(real_agent, "__init__", init_without_navigation)
    completion = Mock(
        return_value=SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "decisions": [
                                    {
                                        "id": "F1",
                                        "suppress": False,
                                        "reason": "uncertain",
                                    }
                                ]
                            }
                        )
                    )
                )
            ],
        )
    )
    monkeypatch.setattr(agent_module.litellm, "completion", completion)
    monkeypatch.setattr(module, "parse_config", lambda: options(model=override))
    assert review.run() == RAW
    kwargs = completion.call_args.kwargs
    assert kwargs["model"] == (override or "openai/default-model")
    assert kwargs["api_base"] == "https://provider.invalid/v1"
    assert kwargs["api_key"] == "fake-test-key"
    assert kwargs["reasoning_effort"] == "low"
    assert kwargs["allowed_openai_params"] == ["reasoning_effort"]
    assert "tools" not in kwargs
    assert real_agent.model == "openai/default-model"
