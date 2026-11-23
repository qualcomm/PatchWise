# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Checkpatch's default path stays offline; filtering is opt-in and fail-open."""

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from git import Actor, Repo

from patchwise.patch_review.ai_agent import agent as agent_module
from patchwise.patch_review.static_analysis import checkpatch as module
from patchwise.patch_review.static_analysis.checkpatch import Checkpatch
from patchwise.patch_review.static_analysis.checkpatch_filter import (
    filter_options,
    parse_report,
)
from patchwise.utils import config

RAW = ":0: WARNING:TYPO_SPELLING: 'SoM' may be misspelled - perhaps 'Some'?\n\ntotal: 0 errors, 1 warnings, 0 checks, 5 lines checked\n"
DECISIONS = [{"id": "F1", "suppress": True, "reason": "SoM is a board abbreviation"}]
VALID_REPLY = json.dumps({"decisions": DECISIONS})
DEFAULT_MODEL = "openai/default-model"


@pytest.fixture
def provider(monkeypatch):
    agent = agent_module.Agent
    monkeypatch.setattr(agent, "model", DEFAULT_MODEL)
    monkeypatch.setattr(agent, "api_base", "https://provider.invalid/v1")
    monkeypatch.setattr(agent, "api_key", "fake-test-key")
    monkeypatch.setattr(agent, "reasoning_effort", "low")

    def init_without_navigation(self, *_args):
        self.model = agent.model
        self.logger = self.get_logger()
        self.current_label = ""
        self.time_waiting_for_ai_response = 0

    monkeypatch.setattr(agent, "__init__", init_without_navigation)
    complete = Mock(return_value=model_reply(VALID_REPLY))
    monkeypatch.setattr(agent_module.litellm, "completion", complete)
    return complete


def model_reply(content):
    message = agent_module.litellm.Message(role="assistant", content=content)
    return SimpleNamespace(usage=None, choices=[SimpleNamespace(message=message)])


@pytest.fixture
def review(monkeypatch, tmp_path, provider):
    # Replace the Docker boundary and run the real classifier and Agent calls.
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
    return item


def options(enabled=True, model=None):
    result = {"enabled": enabled}
    if model is not None:
        result["model"] = model
    return {"static_analysis": {"Checkpatch": {"ai_filter": result}}}


@pytest.mark.parametrize("raw,cfg", [(RAW, {}), (RAW, options(False)), ("", options())])
def test_filter_inactive_does_not_prepare_context_or_call_model(
    review, monkeypatch, provider, raw, cfg
):
    review.docker_manager.run_cmd_with_timer.return_value = raw
    monkeypatch.setattr(module, "parse_config", lambda: cfg)
    assert review.run() == raw
    review.repo.git.show.assert_not_called()
    provider.assert_not_called()


def test_shipped_default_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "USER_CONFIG_PATH", tmp_path / "missing")
    assert filter_options(config.parse_config()) == (False, None)


@pytest.mark.parametrize(
    "cfg", [options("false"), options(1), options(True, ""), {"static_analysis": []}]
)
def test_bad_config_retains_original(review, monkeypatch, provider, cfg):
    monkeypatch.setattr(module, "parse_config", lambda: cfg)
    assert review.run() == RAW
    review.repo.git.show.assert_not_called()
    provider.assert_not_called()


@pytest.mark.parametrize(
    "override,replies",
    [
        (None, [VALID_REPLY]),
        ("openai/filter-model", ['{"decisions":[]}', f"```json\n{VALID_REPLY}\n```"]),
    ],
    ids=["active-model", "override-with-json-retry"],
)
def test_filter_uses_shared_json_completion(
    review, monkeypatch, provider, tmp_path, override, replies
):
    monkeypatch.setattr(module, "parse_config", lambda: options(model=override))
    provider.side_effect = [model_reply(reply) for reply in replies]

    assert review.run() == ""
    assert provider.call_count == len(replies)
    review.repo.git.show.assert_called_once_with("abc123", format="", root=True)
    for call in provider.call_args_list:
        assert call.kwargs["model"] == (override or DEFAULT_MODEL)
        assert call.kwargs["api_base"] == "https://provider.invalid/v1"
        assert call.kwargs["api_key"] == "fake-test-key"
        assert call.kwargs["reasoning_effort"] == "low"
        assert call.kwargs["allowed_openai_params"] == ["reasoning_effort"]
        assert call.kwargs["stream"] is False
        assert "tools" not in call.kwargs
    payload = json.loads(provider.call_args.kwargs["messages"][1]["content"])
    assert payload["commit_message"] == "Support the SoM board"
    assert payload["diff"] == "+SoM"
    assert payload["findings"][0]["id"] == "F1"
    assert agent_module.Agent.model == DEFAULT_MODEL
    (audit_dir,) = (tmp_path / "checkpatch_filter" / "abc123").iterdir()
    assert {path.name for path in audit_dir.iterdir()} == {"raw.txt", "decisions.json"}
    assert (audit_dir / "raw.txt").read_text() == RAW
    assert json.loads((audit_dir / "decisions.json").read_text()) == DECISIONS


def test_json_retry_exhaustion_keeps_raw(review, monkeypatch, provider, tmp_path):
    monkeypatch.setattr(module, "parse_config", lambda: options())
    provider.return_value = model_reply(
        '{"decisions":[{"id":"F1","suppress":true,"reason":null}]}'
    )

    assert review.run() == RAW
    assert provider.call_count == agent_module.AGENT_JSON_RETRIES + 1
    (audit_dir,) = (tmp_path / "checkpatch_filter" / "abc123").iterdir()
    assert list(audit_dir.iterdir()) == [audit_dir / "raw.txt"]
    assert (audit_dir / "raw.txt").read_text() == RAW


@pytest.mark.parametrize("where", ["diff", "agent", "completion"])
def test_filter_setup_failure_keeps_raw(review, monkeypatch, provider, where):
    monkeypatch.setattr(module, "parse_config", lambda: options())
    if where == "diff":
        review.repo.git.show.side_effect = RuntimeError("git failed")
    elif where == "agent":
        monkeypatch.setattr(
            agent_module.Agent,
            "__init__",
            Mock(side_effect=RuntimeError("cache failed")),
        )
    else:
        provider.side_effect = RuntimeError("provider failed")
    assert review.run() == RAW


def test_real_checkpatch_report_parses():
    raw = (Path(__file__).parent / "fixtures" / "checkpatch-report.txt").read_text()
    report = parse_report(raw)
    assert report is not None
    assert len(report.findings) == 8
    assert report.render(set()) == raw


@pytest.mark.parametrize("root_commit", [True, False], ids=["root", "with-parent"])
def test_filter_uses_reviewed_git_commit_not_working_tree(
    review, monkeypatch, provider, tmp_path, root_commit
):
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

    assert review.run() == ""
    provider.assert_called_once()
    payload = json.loads(provider.call_args.kwargs["messages"][1]["content"])
    assert payload["commit_message"] == commit.message
    assert "+/* Support the SoM (System on Module) board */" in payload["diff"]
    assert "Later unrelated" not in payload["diff"]
    assert "Uncommitted" not in payload["diff"]
    assert source.read_text() == "/* Uncommitted unrelated content */\n"
