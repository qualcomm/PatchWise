# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Tests for ScreenController's variable-height footer.

The open-task pane makes the footer grow and shrink mid-run, which moves the
scroll-region boundary. These tests pin the two properties that keeps safe: the
region is re-established at the new boundary, and the rows a shrinking footer
vacates are cleared so no stale footer text is left inside the timeline area."""

import io

import pytest

from patchwise.ui.screen import ScreenController


class _Stream(io.StringIO):
    """A StringIO that looks enough like a tty for blessed to style into it."""

    def isatty(self):
        return True

    def fileno(self):
        raise io.UnsupportedOperation("no fileno")


@pytest.fixture
def ctl():
    c = ScreenController(_Stream(), footer_rows=8)
    c._height, c._width = 24, 80
    c._drawn_footer_rows = c._footer_rows
    return c


def _drain(ctl):
    """Render one frame and return what was written to the stream."""
    ctl._stream.seek(0)
    ctl._stream.truncate()
    ctl._drain_and_render()
    return ctl._stream.getvalue()


def test_footer_adopts_new_height(ctl):
    ctl.set_footer(["a"] * 12)
    assert ctl._footer_rows == 12
    # The timeline region shrinks by exactly the rows the footer gained.
    assert ctl._scroll_rows() == 24 - 12


def test_empty_footer_keeps_previous_height(ctl):
    """An empty list is not a height change — it would collapse the region."""
    ctl.set_footer([])
    assert ctl._footer_rows == 8


def test_footer_cannot_crowd_out_the_timeline(ctl):
    """However many rows a caller hands us, the timeline keeps some rows."""
    ctl.set_footer(["x"] * 100)
    assert ctl._scroll_rows() >= 1
    assert ctl._footer_rows <= 24 - 3


def test_growth_reestablishes_region_and_repaints(ctl):
    _drain(ctl)                       # settle at the initial height
    ctl.set_footer(["row"] * 11)
    out = _drain(ctl)
    assert ctl.term.csr(0, ctl._scroll_bottom()) in out
    assert ctl._drawn_footer_rows == 11
    assert "row" in out


def test_shrink_clears_the_rows_the_footer_vacated(ctl):
    """A footer that shrinks leaves its old top rows inside the new timeline
    region; those rows must be cleared or stale text stays on screen."""
    ctl.set_footer(["tasks"] * 14)
    _drain(ctl)
    assert ctl._drawn_footer_rows == 14

    ctl.set_footer(["status"] * 8)
    out = _drain(ctl)
    # Clearing starts at the topmost footer row of either geometry (the old,
    # higher one here) and runs to the bottom of the screen.
    old_first = 24 - 14
    assert ctl.term.move(old_first, 0) in out
    assert ctl._drawn_footer_rows == 8


def test_no_regeometry_when_height_is_stable(ctl):
    """A same-height footer update is a plain repaint — no region churn."""
    ctl.set_footer(["a"] * 8)
    _drain(ctl)
    ctl.set_footer(["b"] * 8)
    out = _drain(ctl)
    assert ctl.term.csr(0, ctl._scroll_bottom()) not in out
    assert "b" in out


def test_visible_count_clamped_when_footer_grows(ctl):
    """The timeline fill count must stay inside a region that just shrank, or
    the next line would be written underneath the footer."""
    ctl._visible_count = 15
    ctl.set_footer(["t"] * 14)
    _drain(ctl)
    assert ctl._visible_count <= ctl._scroll_rows()


def test_height_change_inside_on_resize_is_not_lost():
    """The resize callback re-renders the footer and may change its height as a
    side effect. That happens after the region was emitted for the old height, so
    it must be picked up as a pending change on the next frame rather than being
    marked as already drawn."""
    stream = _Stream()
    state = {"rows": 8}

    ctl = ScreenController(stream, footer_rows=8)

    def on_resize():
        # Simulates the dashboard growing the pane while re-rendering at the new
        # width (a task arrives during the resize frame).
        ctl.set_footer(["grown"] * state["rows"])

    ctl._on_resize = on_resize
    ctl._height, ctl._width = 24, 80
    ctl._drawn_footer_rows = ctl._footer_rows
    _drain(ctl)

    state["rows"] = 13
    ctl._resize.set()
    _drain(ctl)
    # The callback grew the footer to 13; the region was emitted for 8, so the
    # controller must still see a height change outstanding.
    assert ctl._footer_rows == 13
    assert ctl._drawn_footer_rows == 8

    out = _drain(ctl)
    assert ctl._drawn_footer_rows == 13
    assert ctl.term.csr(0, ctl._scroll_bottom()) in out
