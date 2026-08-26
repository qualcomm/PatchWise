# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Tests for the dashboard's live open-task pane in the pinned footer.

The pane's contract: a task appears when the agent adds it, disappears when the
agent completes it, and the footer grows and shrinks with it (so an idle run
reserves no rows for a checklist that isn't there)."""

import re

import pytest

from patchwise.ui import events
from patchwise.ui.dashboard import _FOOTER_ROWS, _TASK_ROWS, Dashboard

from rich.console import Console


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _plain(lines):
    """Footer rows with ANSI styling stripped, for content assertions."""
    return [_ANSI.sub("", ln) for ln in lines]


@pytest.fixture
def dash():
    # No controller: the dashboard renders to strings, which is all we assert on.
    return Dashboard(Console(no_color=True, width=100))


def _task(dash, action, label="exec:u1", **fields):
    dash.on_event(events.TASK, {"action": action, "label": label, **fields})


def _footer(dash):
    return _plain(dash._footer_lines(100))


def test_no_pane_when_no_tasks(dash):
    """With no tasks the footer keeps its fixed height and shows no pane."""
    lines = _footer(dash)
    assert len(lines) == _FOOTER_ROWS
    assert not any("open" in ln for ln in lines)


def test_added_task_appears_and_footer_grows(dash):
    _task(dash, "add", id="t1", description="check locking in probe()")
    lines = _footer(dash)
    body = "\n".join(lines)
    assert "t1" in body
    assert "check locking in probe()" in body
    assert "1 open" in body
    # A pane costs its divider plus a row per task.
    assert len(lines) > _FOOTER_ROWS


def test_completed_task_is_removed(dash):
    _task(dash, "add", id="t1", description="first")
    _task(dash, "add", id="t2", description="second")
    assert "2 open" in "\n".join(_footer(dash))

    _task(dash, "complete", id="t1", result="clean")
    body = "\n".join(_footer(dash))
    assert "t1" not in body        # completed tasks leave the list
    assert "t2" in body
    assert "1 open" in body
    assert "1 done" in body


def test_footer_shrinks_back_when_checklist_drains(dash):
    """The pane is transient: once every task completes the footer returns to
    exactly its fixed height, leaving no reserved rows behind."""
    base = len(_footer(dash))
    _task(dash, "add", id="t1", description="first")
    _task(dash, "add", id="t2", description="second")
    assert len(_footer(dash)) > base

    _task(dash, "complete", id="t1")
    _task(dash, "complete", id="t2")
    lines = _footer(dash)
    assert len(lines) == base == _FOOTER_ROWS
    assert not any("open" in ln for ln in lines)


def test_tasks_reset_when_unit_changes(dash):
    """Each exec unit keeps its own checklist, so a new label starts empty — a
    finished unit's open tasks must not linger in the next unit's pane."""
    _task(dash, "add", label="exec:u1", id="t1", description="unit one work")
    _task(dash, "add", label="exec:u2", id="t9", description="unit two work")
    body = "\n".join(_footer(dash))
    assert "t9" in body and "unit two work" in body
    assert "t1" not in body
    assert "1 open" in body


def test_resume_marks_pane_and_syncs_open_ids(dash):
    """A resume round is flagged, and its open_ids (read from the on-disk
    checklist) become the authoritative list — repairing any missed event."""
    _task(dash, "add", id="t1", description="kept")
    _task(dash, "add", id="t2", description="already done, event missed")
    _task(dash, "resume", round=1, cap=2, open_ids=["t1"])
    body = "\n".join(_footer(dash))
    assert "resume 1/2" in body
    assert "t1" in body
    assert "t2" not in body       # pipeline no longer considers it open
    assert "1 open" in body


def test_overflow_is_summarised_not_unbounded(dash):
    """More tasks than the pane's row budget: the newest stay visible and the
    rest are counted, so the footer can't push the timeline off screen."""
    n = _TASK_ROWS + 4
    for i in range(n):
        _task(dash, "add", id=f"t{i}", description=f"task {i}")
    lines = _footer(dash)
    body = "\n".join(lines)
    assert f"{n} open" in body
    assert f"… {n - (_TASK_ROWS - 1)} more open" in body
    assert f"t{n - 1}" in body     # newest shown
    assert len(lines) <= _FOOTER_ROWS + _TASK_ROWS + 1


def test_pane_is_footer_only_not_in_the_summary(dash):
    """The checklist is live state for the footer while work is in flight; the
    final summary reports findings, not task bookkeeping."""
    _task(dash, "add", id="t1")
    _task(dash, "add", id="t2")
    _task(dash, "complete", id="t1")
    dash.on_event(events.RUN_DONE, {"summary": {}})

    cap = Console(no_color=True, width=100)
    with cap.capture() as c:
        cap.print(dash.summary_panel())
    body = _ANSI.sub("", c.get())
    assert "task" not in body.lower()


def test_bad_task_events_do_not_crash(dash):
    """The bus contract is that a UI bug can't break a review; the pane must
    tolerate malformed payloads rather than rely on that safety net."""
    for payload in ({}, {"action": "add"}, {"action": "complete", "id": "nope"},
                    {"action": "resume", "open_ids": None},
                    {"action": "bogus", "id": "x"}, {"action": "add", "id": None}):
        dash.on_event(events.TASK, payload)
    _footer(dash)   # still renders
