# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Severity labels are opt-in and must not change the false-positive policy."""

import json
import logging
from types import SimpleNamespace

import pytest

from patchwise.patch_review.ai_review.ai_code_review import AiCodeReview
from patchwise.patch_review.ai_review import ai_code_review
from patchwise.patch_review.ai_agent import agent as agent_module
from patchwise.patch_review.ai_agent.agent import Agent
from patchwise.utils import config


@pytest.fixture
def user_config(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "USER_CONFIG_PATH", path)
    monkeypatch.setattr(ai_code_review, "SANDBOX_PATH", tmp_path)
    monkeypatch.setattr(agent_module, "SANDBOX_PATH", tmp_path)
    return path


@pytest.mark.parametrize("impact", ["low", "medium", "high", "", None, "unexpected"])
@pytest.mark.parametrize("proven_drop", [False, True])
def test_render_kept_default_is_unchanged(impact, proven_drop):
    entry = {"finding": "  Buffer leaks.  ", "impact": impact}
    if proven_drop:
        entry.update(verdict="drop", proof="The buffer is freed on the error path.")
    expected = "Buffer leaks."
    if proven_drop and impact not in ("low", "medium"):
        expected = "[likely false positive] " + expected
    assert AiCodeReview._render_kept(entry) == expected
    assert AiCodeReview._render_kept(entry, output_severity=False) == expected


@pytest.mark.parametrize("impact", ["low", "medium", "high", " HIGH ", "Medium"])
def test_render_kept_prefixes_known_impact(impact):
    entry = {"finding": "Buffer leaks.", "impact": impact}
    assert AiCodeReview._render_kept(entry, output_severity=True) == (
        f"[{impact.strip().lower()}] Buffer leaks."
    )


@pytest.mark.parametrize("impact", ["", None, "critical", 1, {}, []])
def test_render_kept_does_not_invent_severity(impact):
    entry = {"finding": "Buffer leaks.", "impact": impact}
    assert AiCodeReview._render_kept(entry, output_severity=True) == "Buffer leaks."


def test_render_kept_missing_impact_is_unrated():
    assert (
        AiCodeReview._render_kept({"finding": "Buffer leaks."}, output_severity=True)
        == "Buffer leaks."
    )


@pytest.mark.parametrize("finding", ["", "  ", None])
def test_render_kept_does_not_turn_empty_finding_into_label(finding):
    entry = {
        "finding": finding,
        "impact": "high",
        "verdict": "drop",
        "proof": "proven false positive",
    }
    assert AiCodeReview._render_kept(entry, output_severity=True) == ""


def test_render_kept_combines_severity_and_false_positive_prefixes():
    entry = {
        "finding": "Buffer leaks.",
        "impact": "high",
        "verdict": "drop",
        "proof": "The buffer is freed on the error path.",
    }
    assert AiCodeReview._render_kept(entry, output_severity=True) == (
        "[high] [likely false positive] Buffer leaks."
    )
    assert not AiCodeReview._is_dropped(entry)


def _review(tmp_path):
    review = AiCodeReview.__new__(AiCodeReview)
    review.docker_manager = SimpleNamespace(container_name="__severity_test__")
    review.logger = logging.getLogger(__name__)
    review.commit_message = "Fix buffer handling"
    review.diff = "\n".join(
        [
            "diff --git a/test.c b/test.c",
            "--- a/test.c",
            "+++ b/test.c",
            "@@ -1 +1 @@",
            "-old();",
            "+new();",
        ]
    )
    review.commit = SimpleNamespace(parents=[object()])
    review.build_dir = tmp_path
    return review


@pytest.mark.parametrize("setting", [None, False, True])
@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize("output_format", ["inline", "gerrit"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_filter_uses_config_without_changing_verdicts(
    tmp_path, user_config, setting, streamed, output_format, cleanup_fails
):
    user_config.write_text(f"ai:\n  output_format: {output_format}\n")
    if setting is not None:
        user_config.write_text(
            user_config.read_text()
            + f"  code_review:\n    output_severity: {str(setting).lower()}\n"
        )
    entries = [
        {"finding": "Low finding.", "impact": "low"},
        {"finding": "Medium finding.", "impact": "medium"},
        {
            "finding": "High finding.",
            "impact": "high",
            "verdict": "drop",
            "proof": "A concrete disproof.",
        },
        {
            "finding": "Dropped finding.",
            "impact": "low",
            "verdict": "drop",
            "proof": "A concrete disproof.",
        },
        {"finding": "Unrated finding."},
    ]
    # Exercise the production verdict writer and reader, then the actual cleanup
    # and output renderers. Only model responses are replaced.
    entries = [
        {"impact": "", "verdict": "", "reason": "", "proof": "", **entry}
        for entry in entries
    ]
    agent = Agent.__new__(Agent)
    calls = []

    def run_agent_loop(*args, **kwargs):
        if streamed:
            for entry in entries:
                assert agent._tool_record_verdict(**entry)["ok"]

    def complete_until_json(messages, **kwargs):
        calls.append(agent.current_label)
        if agent.current_label == "fp-filter":
            assert not streamed
            return entries
        assert agent.current_label == "cleanup"
        text = "\n\n".join(expected)
        assert text in messages[1]["content"]
        if cleanup_fails:
            return None
        return [
            {"finding": finding, "start_line": "P6", "end_line": "P6"}
            for finding in expected
        ]

    review = _review(tmp_path)
    agent.run_agent_loop = run_agent_loop
    agent.complete_until_json = complete_until_json
    review.agent = agent
    findings = "\n".join(f"### {entry['finding']}" for entry in entries)

    expected = [
        "Low finding.",
        "Medium finding.",
        "[likely false positive] High finding.",
        "Unrated finding.",
    ]
    if setting:
        expected[:3] = [
            f"[{impact}] {text}"
            for impact, text in zip(("low", "medium", "high"), expected[:3])
        ]
    final, kept, before, floored = review._fp_filter_phase([({}, findings)])

    assert calls == (["cleanup"] if streamed else ["fp-filter", "cleanup"])
    if output_format == "gerrit":
        comments = json.loads(final)
        path = "/PATCHSET_LEVEL" if cleanup_fails else "test.c"
        messages = [comment["message"] for comment in comments[path]]
        assert messages == (["\n\n".join(expected)] if cleanup_fails else expected)
    else:
        for finding in expected:
            assert finding in final
        if cleanup_fails:
            assert final == "\n\n".join(expected)
    assert "Dropped finding." not in final
    assert (kept, before, floored) == (4, 5, 1)
    saved = json.loads((tmp_path / "ai_code_review" / "fp_verdicts.json").read_text())
    assert saved["verdicts"] == entries


@pytest.mark.parametrize("output_format", ["inline", "gerrit"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_cleanup_preserves_labels_in_each_output_format(
    tmp_path, user_config, output_format, cleanup_fails
):
    user_config.write_text(f"ai:\n  output_format: {output_format}\n")
    text = "[high] [likely false positive] Buffer leaks."
    review = _review(tmp_path)

    def complete_until_json(messages, **kwargs):
        instructions = messages[0]["content"][-1]["text"]
        assert "[low]" in instructions
        assert "[medium]" in instructions
        assert "[high]" in instructions
        assert "[likely false positive]" in instructions
        assert text in messages[1]["content"]
        if cleanup_fails:
            return None
        return [{"finding": text, "start_line": "P6", "end_line": "P6"}]

    review.agent = SimpleNamespace(complete_until_json=complete_until_json)
    final = review.format_chat_response(text)
    if output_format == "inline":
        assert text in final
        if cleanup_fails:
            assert final == text
    else:
        comments = json.loads(final)
        path = "/PATCHSET_LEVEL" if cleanup_fails else "test.c"
        assert comments[path][0]["message"] == text


def test_default_config_disables_severity(user_config):
    assert config.parse_config()["ai"]["code_review"]["output_severity"] is False
