# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Offline regressions for conservative checkpatch filtering."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest

from patchwise.patch_review.static_analysis.checkpatch_filter import (
    filter_options,
    filter_report,
    parse_report,
)

WARNING = ":0: WARNING:TYPO_SPELLING: 'SoM' may be misspelled - perhaps 'Some'?\n\n"
ERROR = (
    "drivers/test.c:12: ERROR:TRAILING_WHITESPACE: trailing whitespace\n+bad line \n\n"
)
CHECK = "drivers/test.c:15: CHECK:LINE_SPACING: Please use a blank line\n+next line\n\n"
SUMMARY = "total: 1 errors, 1 warnings, 1 checks, 42 lines checked\n"
RAW = WARNING + ERROR + CHECK + SUMMARY


def response(suppressed=()):
    return json.dumps(
        {
            "decisions": [
                {
                    "id": ident,
                    "suppress": ident in suppressed,
                    "reason": "Evidence for " + ident,
                }
                for ident in ("F1", "F2", "F3")
            ]
        }
    )


def run_filter(tmp_path, complete, raw=RAW):
    return filter_report(
        raw, "Commit about SoM", "diff --git a/test b/test\n", complete, tmp_path
    )


def test_parse_complete_report_preserves_original_records():
    report = parse_report(RAW)
    assert report is not None
    assert [(f.id, f.level, f.text) for f in report.findings] == [
        ("F1", "WARNING", WARNING),
        ("F2", "ERROR", ERROR),
        ("F3", "CHECK", CHECK),
    ]
    assert report.lines_checked == "42"
    assert report.has_checks is True


@pytest.mark.parametrize(
    "raw",
    [
        "",
        WARNING,
        WARNING + "total: 0 errors, 2 warnings, 42 lines checked\n",
        WARNING + "total: 0 errors, 1 warnings, 1 checks, 42 lines checked\n",
        WARNING + "total: one errors, 1 warnings, 42 lines checked\n",
        WARNING + "total: -1 errors, 1 warnings, 42 lines checked\n",
        WARNING + "total: 0 errors, 1 warnings, 42 lines checked\ntrailing garbage\n",
        "unexpected preamble\n" + RAW,
        "\n" + RAW,
        WARNING.replace("\n\n", "\nNOTE:UNKNOWN: unrelated diagnostic\n\n")
        + ERROR
        + CHECK
        + SUMMARY,
        WARNING.replace("\n\n", "\nfatal: checkpatch processing failed\n\n")
        + ERROR
        + CHECK
        + SUMMARY,
        "NOTE:TYPO_SPELLING: unknown diagnostic\n" + SUMMARY,
        "WARNING:TYPO_SPELLING missing colon\n" + SUMMARY,
        "total: 0 errors, 0 warnings, 42 lines checked\n",
        RAW + SUMMARY,
    ],
)
def test_unrecognized_report_is_unchanged_without_model_call(tmp_path, raw):
    complete = Mock(side_effect=AssertionError("model must not run"))
    assert parse_report(raw) is None
    assert run_filter(tmp_path, complete, raw) == raw
    complete.assert_not_called()
    (audit,) = tmp_path.iterdir()
    assert (audit / "raw.txt").read_text() == raw
    assert json.loads((audit / "status.json").read_text()) == {
        "status": "unrecognized_report",
        "filtered": False,
    }


def test_mixed_suppression_preserves_original_text_and_recounts(tmp_path):
    complete = Mock(return_value=response({"F1"}))
    result = run_filter(tmp_path, complete)
    assert (
        result
        == ERROR + CHECK + "total: 1 errors, 0 warnings, 1 checks, 42 lines checked\n"
    )
    (messages,) = complete.call_args.args
    assert [m["role"] for m in messages] == ["system", "user"]
    data = json.loads(messages[1]["content"])
    assert data["commit_message"] == "Commit about SoM"
    assert data["diff"] == "diff --git a/test b/test\n"
    assert [f["text"] for f in data["findings"]] == [WARNING, ERROR, CHECK]


def test_suppression_without_optional_checks_summary(tmp_path):
    raw = WARNING + ERROR + "total: 1 errors, 1 warnings, 42 lines checked\n"
    decisions = json.loads(response({"F1"}))
    decisions["decisions"].pop()
    result = run_filter(tmp_path, lambda _: json.dumps(decisions), raw)
    assert result == ERROR + "total: 1 errors, 0 warnings, 42 lines checked\n"


def test_all_suppressed_is_empty(tmp_path):
    assert run_filter(tmp_path, lambda _: response({"F1", "F2", "F3"})) == ""


@pytest.mark.parametrize("raw", [RAW, RAW.rstrip("\n"), "\n" + RAW])
def test_no_suppression_is_byte_identical(tmp_path, raw):
    assert run_filter(tmp_path, lambda _: response(), raw) == raw


def test_audit_keeps_raw_model_response_decisions_and_filtered_text(tmp_path):
    reply = response({"F1"})
    result = run_filter(tmp_path, lambda _: reply)
    (audit,) = tmp_path.iterdir()
    assert (audit / "raw.txt").read_text() == RAW
    assert (audit / "response.txt").read_text() == reply
    assert (
        json.loads((audit / "decisions.json").read_text())
        == json.loads(reply)["decisions"]
    )
    assert (audit / "filtered.txt").read_text() == result


def test_callback_failure_retains_raw_and_failure_audit(tmp_path):
    complete = Mock(side_effect=RuntimeError("model unavailable"))
    assert run_filter(tmp_path, complete) == RAW
    (audit,) = tmp_path.iterdir()
    assert (audit / "raw.txt").read_text() == RAW
    assert json.loads((audit / "status.json").read_text()) == {
        "status": "failed",
        "filtered": False,
        "error": "RuntimeError",
    }


def invalid_responses():
    yield "not JSON"
    yield "```json\n" + response({"F1"}) + "\n```"
    yield "null"
    yield "[]"
    yield '{"decisions": null}'
    yield '{"decisions": []}'
    for field, value in [
        ("id", "F99"),
        ("id", []),
        ("suppress", "true"),
        ("suppress", 1),
        ("suppress", None),
        ("reason", ""),
        ("reason", "  "),
        ("reason", 1),
    ]:
        data = json.loads(response({"F1"}))
        data["decisions"][0][field] = value
        yield json.dumps(data)
    data = json.loads(response({"F1"}))
    data["decisions"][1] = data["decisions"][0]
    yield json.dumps(data)
    data = json.loads(response({"F1"}))
    data["decisions"].pop()
    yield json.dumps(data)
    data = json.loads(response({"F1"}))
    data["decisions"][0]["unexpected"] = True
    yield json.dumps(data)
    data = json.loads(response({"F1"}))
    data["unexpected"] = True
    yield json.dumps(data)


@pytest.mark.parametrize("reply", list(invalid_responses()))
def test_invalid_decisions_always_keep_raw(tmp_path, reply):
    assert run_filter(tmp_path, lambda _: reply) == RAW
    (audit,) = tmp_path.iterdir()
    assert (audit / "raw.txt").read_text() == RAW
    assert (audit / "response.txt").read_text() == reply
    status = json.loads((audit / "status.json").read_text())
    assert status["status"] == "failed"
    assert status["filtered"] is False


def test_audit_failure_before_model_keeps_raw(tmp_path):
    audit_root = tmp_path / "not-a-directory"
    audit_root.write_text("occupied")
    complete = Mock()
    assert run_filter(audit_root, complete) == RAW
    complete.assert_not_called()


def test_audit_failure_after_model_keeps_raw(tmp_path, monkeypatch):
    original = Path.write_text

    def fail_decisions(path, *args, **kwargs):
        if path.name == "decisions.json":
            raise OSError("audit disk full")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_decisions)
    assert run_filter(tmp_path, lambda _: response({"F1"})) == RAW


def test_concurrent_runs_keep_separate_audits(tmp_path):
    count = 8

    def work(index):
        raw = RAW.replace("42 lines", f"{index + 1} lines")
        return run_filter(tmp_path, lambda _: response({"F1"}), raw)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(work, range(count)))
    audits = list(tmp_path.iterdir())
    assert len(audits) == count
    assert {(a / "raw.txt").read_text() for a in audits} == {
        RAW.replace("42 lines", f"{i + 1} lines") for i in range(count)
    }
    assert {(a / "filtered.txt").read_text() for a in audits} == set(results)
    assert all((a / "decisions.json").is_file() for a in audits)


@pytest.mark.parametrize("enabled", [False, True])
def test_filter_options_boolean_only(enabled):
    config = {
        "static_analysis": {
            "Checkpatch": {"ai_filter": {"enabled": enabled, "model": "provider/model"}}
        }
    }
    assert filter_options(config) == (enabled, "provider/model")
    assert filter_options({}) == (False, None)


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None, [], {}])
def test_invalid_enabled_values_are_rejected(value):
    with pytest.raises(ValueError, match="boolean"):
        filter_options(
            {"static_analysis": {"Checkpatch": {"ai_filter": {"enabled": value}}}}
        )


@pytest.mark.parametrize("value", ["", " ", 7, False, []])
def test_invalid_model_values_are_rejected(value):
    with pytest.raises(ValueError, match="nonempty string"):
        filter_options(
            {"static_analysis": {"Checkpatch": {"ai_filter": {"model": value}}}}
        )
