# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Unit tests for the scroll-region terminal controller (no LLM/docker/tty).

These drive the controller against an in-memory stream and exercise one render
frame at a time, so the assertions are deterministic — no threads, no timing,
no PTY (which prior sessions proved unreliable for this code)."""

import io

from patchwise.ui.screen import ScreenController


def _make(height=24, width=80, footer_rows=6):
    """A controller wired to an in-memory stream with fixed geometry. Geometry is
    set directly (and `_measure` neutered) so a 'resize' is just a field change —
    no real tty needed."""
    buf = io.StringIO()
    c = ScreenController(buf, footer_rows=footer_rows)
    c._measure = lambda: None  # geometry is driven by the test, not a tty
    c._height, c._width = height, width
    return c, buf


def test_start_sets_scroll_region_and_clears_screen():
    c, buf = _make(height=24, footer_rows=6)
    c._emit_start()
    out = buf.getvalue()
    # 24 rows, 6 footer → 18 scroll rows → region rows 1..18 (csr is 0-based in,
    # 1-based out). The screen is cleared for a clean slate and the cursor parks
    # at the top of the region (the timeline fills downward).
    assert c.term.csr(0, 17) in out
    assert c.term.move(0, 0) in out
    assert (c.term.clear_eos or "") in out
    assert c.term.hide_cursor in out


def test_print_block_fills_from_top_and_repaints_footer():
    c, buf = _make()
    c._emit_start()
    c.set_footer([f"F{i}" for i in range(6)])
    c.print_block(["alpha", "beta"])
    c._drain_and_render()
    out = buf.getvalue()
    # The timeline fills from the top: alpha at row 0, beta at row 1.
    assert c.term.move(0, 0) in out and c.term.move(1, 0) in out
    assert "alpha" in out and "beta" in out
    # Footer lines are painted at their absolute rows (first footer row 0-based
    # 18 → row 19) and all six are present.
    for i in range(6):
        assert f"F{i}" in out
    assert c.term.move(18, 0) in out


def test_grow_reestablishes_region_redraws_footer_once_without_repainting_timeline():
    c, buf = _make(height=24, footer_rows=6)
    c._emit_start()
    c.set_footer([f"F{i}" for i in range(6)])
    c.print_block(["alpha", "beta"])
    c._drain_and_render()

    # Grow the window to 30 rows and signal a resize. `_measure` (called inside
    # the resize handler) flips the height, mirroring the real flow where
    # `_height` is still the old value until the handler re-measures.
    buf.seek(0)
    buf.truncate(0)
    c._measure = lambda: setattr(c, "_height", 30)
    c._resize.set()
    c._drain_and_render()
    out = buf.getvalue()

    # New region: 30 - 6 = 24 scroll rows → bottom 0-based 23; footer at 24..29.
    assert c.term.csr(0, 23) in out
    # The timeline is owned by the terminal's reflow — we do NOT repaint it, so a
    # resize can't re-emit already-scrolled lines and duplicate them into
    # scrollback.
    assert "alpha" not in out and "beta" not in out
    # The footer band (from the old first row 18 down) is cleared to wipe any
    # stale footer, then the footer is redrawn exactly once at the new first
    # row 24.
    assert c.term.move(18, 0) in out
    assert out.count("F0") == 1
    assert c.term.move(24, 0) in out


def test_shrink_reestablishes_region_redraws_footer_once_without_repainting_timeline():
    c, buf = _make(height=30, footer_rows=6)
    c._emit_start()
    c.set_footer([f"F{i}" for i in range(6)])
    c.print_block(["alpha", "beta"])
    c._drain_and_render()

    buf.seek(0)
    buf.truncate(0)
    c._measure = lambda: setattr(c, "_height", 24)   # shrink
    c._resize.set()
    c._drain_and_render()
    out = buf.getvalue()

    # New region: 24 - 6 = 18 scroll rows → bottom 0-based 17; footer at 18..23.
    assert c.term.csr(0, 17) in out
    assert "alpha" not in out and "beta" not in out
    # Clear from the topmost footer row (new first 18, since old first 24 > 18)
    # down, then redraw the footer once at row 18.
    assert c.term.move(18, 0) in out
    assert out.count("F0") == 1


def test_stop_resets_region_and_restores_cursor():
    c, buf = _make(height=24, footer_rows=6)
    c._emit_start()
    buf.seek(0)
    buf.truncate(0)
    c._emit_stop()
    out = buf.getvalue()
    assert c.term.csr(0, 23) in out          # region reset to full screen
    assert (c.term.normal_cursor or "") in out
