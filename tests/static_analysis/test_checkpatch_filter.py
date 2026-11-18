# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Offline regressions for conservative checkpatch filtering."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest

from patchwise.patch_review.static_analysis.checkpatch_filter import (
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
    return {
        "decisions": [
            {
                "id": ident,
                "suppress": ident in suppressed,
                "reason": "Evidence for " + ident,
            }
            for ident in ("F1", "F2", "F3")
        ]
    }


def json_reply(value):
    return lambda _messages, validate: value if validate(value) else None


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
    assert run_filter(tmp_path, complete, raw) == raw
    complete.assert_not_called()


def test_mixed_suppression_preserves_original_text_and_recounts(tmp_path):
    result = run_filter(tmp_path, json_reply(response({"F1"})))
    assert (
        result
        == ERROR + CHECK + "total: 1 errors, 0 warnings, 1 checks, 42 lines checked\n"
    )


def test_suppression_without_optional_checks_summary(tmp_path):
    raw = WARNING + ERROR + "total: 1 errors, 1 warnings, 42 lines checked\n"
    value = response({"F1"})
    value["decisions"].pop()
    result = run_filter(tmp_path, json_reply(value), raw)
    assert result == ERROR + "total: 1 errors, 0 warnings, 42 lines checked\n"


def test_all_suppressed_is_empty(tmp_path):
    assert run_filter(tmp_path, json_reply(response({"F1", "F2", "F3"}))) == ""


@pytest.mark.parametrize("raw", [RAW, RAW.rstrip("\n")])
def test_no_suppression_is_byte_identical(tmp_path, raw):
    assert run_filter(tmp_path, json_reply(response()), raw) == raw


def invalid_responses():
    yield None
    yield []
    yield {"decisions": None}
    yield {"decisions": []}
    for field, value in [
        ("id", "F99"),
        ("id", []),
        ("suppress", "true"),
        ("suppress", 1),
        ("suppress", None),
        ("reason", ""),
        ("reason", "  "),
        ("reason", 1),
        ("reason", None),
        ("unexpected", True),
    ]:
        data = response({"F1"})
        data["decisions"][0][field] = value
        yield data
    data = response({"F1"})
    data["decisions"][1] = data["decisions"][0]
    yield data
    data = response({"F1"})
    data["decisions"].pop()
    yield data
    yield {**response({"F1"}), "unexpected": True}


@pytest.mark.parametrize("reply", list(invalid_responses()))
def test_invalid_decisions_always_keep_raw(tmp_path, reply):
    assert run_filter(tmp_path, json_reply(reply)) == RAW


@pytest.mark.parametrize("filename, calls", [("raw.txt", 0), ("decisions.json", 1)])
def test_audit_write_failure_keeps_raw(tmp_path, monkeypatch, filename, calls):
    original = Path.write_text

    def fail_write(path, *args, **kwargs):
        if path.name == filename:
            raise OSError("audit disk full")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_write)
    complete = Mock(side_effect=json_reply(response({"F1"})))
    assert run_filter(tmp_path, complete) == RAW
    assert complete.call_count == calls


def test_concurrent_runs_keep_separate_audits(tmp_path):
    reports = {RAW, RAW.replace("42 lines", "1 lines")}
    complete = json_reply(response({"F1"}))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda raw: run_filter(tmp_path, complete, raw), reports)
        )
    assert all("TYPO_SPELLING" not in result for result in results)
    assert {p.read_text() for p in tmp_path.glob("run-*/raw.txt")} == reports
    assert len(list(tmp_path.glob("run-*/decisions.json"))) == len(reports)
