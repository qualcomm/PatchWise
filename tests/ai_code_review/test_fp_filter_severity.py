# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Unit tests for `ai.code_review.output_severity` (no LLM/docker/git).

The false-positive filter rates every finding's `impact`. With the option on,
each kept finding is prefixed with that rating, the same way a floored finding
is prefixed `[likely false positive]`."""

import json
import logging
import types

import pytest
import yaml

from patchwise.patch_review.ai_review import ai_code_review as acr
from patchwise.patch_review.ai_review.ai_code_review import AiCodeReview
from patchwise.utils import config


def _entry(impact, verdict="keep", proof=""):
    return {
        "finding": "foo.c:12: buf leaks on the error path.",
        "impact": impact,
        "verdict": verdict,
        "reason": "r",
        "proof": proof,
    }


PROOF = "guide rule 3: kfree(buf) runs at out_free on line 40"


# ---- _render_kept ------------------------------------------------------------


def test_render_kept_has_no_severity_by_default():
    assert (
        AiCodeReview._render_kept(_entry("medium"))
        == "foo.c:12: buf leaks on the error path."
    )


@pytest.mark.parametrize("impact", ["high", "medium", "low"])
def test_render_kept_prefixes_severity_when_enabled(impact):
    assert (
        AiCodeReview._render_kept(_entry(impact), output_severity=True)
        == f"[{impact}] foo.c:12: buf leaks on the error path."
    )


def test_render_kept_normalises_the_impact_rating():
    assert AiCodeReview._render_kept(_entry("  Medium "), True).startswith("[medium] ")


def test_render_kept_severity_goes_before_likely_false_positive():
    entry = _entry("high", verdict="drop", proof=PROOF)
    assert AiCodeReview._render_kept(entry) == (
        "[likely false positive] foo.c:12: buf leaks on the error path."
    )
    assert AiCodeReview._render_kept(entry, True) == (
        "[high] [likely false positive] foo.c:12: buf leaks on the error path."
    )


@pytest.mark.parametrize("impact", ["", "critical", None])
def test_render_kept_omits_severity_the_filter_did_not_give(impact):
    entry = _entry(impact)
    if impact is None:
        del entry["impact"]
    assert (
        AiCodeReview._render_kept(entry, True)
        == "foo.c:12: buf leaks on the error path."
    )


def test_render_kept_empty_finding_stays_empty():
    entry = _entry("low")
    entry["finding"] = "  "
    assert AiCodeReview._render_kept(entry, True) == ""


# ---- ai_output_severity ------------------------------------------------------


def test_default_config_disables_output_severity():
    defaults = yaml.safe_load(config.DEFAULT_CONFIG_PATH.read_text())
    assert defaults["ai"]["code_review"]["output_severity"] is False


def _with_ai(monkeypatch, ai):
    monkeypatch.setattr(config, "parse_config", lambda: {"ai": ai})


@pytest.mark.parametrize(
    "ai, expected",
    [
        ({}, False),
        ({"code_review": None}, False),
        ({"code_review": {}}, False),
        ({"code_review": {"output_severity": False}}, False),
        ({"code_review": {"output_severity": True}}, True),
    ],
)
def test_ai_output_severity_reads_the_option(monkeypatch, ai, expected):
    _with_ai(monkeypatch, ai)
    assert config.ai_output_severity() is expected


@pytest.mark.parametrize(
    "ai",
    [
        {"code_review": {"output_severity": "yes"}},
        {"code_review": {"output_severity": 1}},
        {"code_review": "on"},
    ],
)
def test_ai_output_severity_rejects_bad_values(monkeypatch, ai):
    _with_ai(monkeypatch, ai)
    with pytest.raises(ValueError, match="ai.code_review"):
        config.ai_output_severity()


# ---- _fp_filter_phase --------------------------------------------------------


def _filter_shell(tmp_path, verdicts):
    """An AiCodeReview shell whose agent "streams" `verdicts` and whose
    cleanup pass returns its input, so the kept text can be read directly."""
    obj = AiCodeReview.__new__(AiCodeReview)
    obj.docker_manager = types.SimpleNamespace(container_name="__test_shell__")
    obj.logger = logging.getLogger("test_fp_filter_severity")
    path = tmp_path / "fp_verdicts.jsonl"

    def run_agent_loop(*args, **kwargs):
        path.write_text("\n".join(json.dumps(v) for v in verdicts))

    obj.agent = types.SimpleNamespace(
        current_label="",
        verdicts_path_for=lambda label: path,
        run_agent_loop=run_agent_loop,
    )
    obj._fp_filter_system_prompt = lambda: ("sys",)
    obj.format_chat_response = lambda text: text
    obj._dump = lambda name, content: None
    return obj


@pytest.mark.parametrize(
    "enabled, expected",
    [
        (False, "a.c:1: one\n\n[likely false positive] b.c:2: two"),
        (True, "[medium] a.c:1: one\n\n[high] [likely false positive] b.c:2: two"),
    ],
)
def test_fp_filter_phase_follows_the_option(tmp_path, monkeypatch, enabled, expected):
    monkeypatch.setattr(acr, "ai_output_severity", lambda: enabled)
    verdicts = [
        {"finding": "a.c:1: one", "impact": "medium", "verdict": "keep", "proof": ""},
        {"finding": "b.c:2: two", "impact": "high", "verdict": "drop", "proof": PROOF},
        {"finding": "c.c:3: three", "impact": "low", "verdict": "drop", "proof": PROOF},
    ]
    obj = _filter_shell(tmp_path, verdicts)
    final, kept, before, floored = obj._fp_filter_phase(
        [({}, "### a.c:1: one\n\n### b.c:2: two\n\n### c.c:3: three")]
    )
    assert final == expected
    assert (kept, before, floored) == (2, 3, 1)
