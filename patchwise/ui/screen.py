# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""A scroll-region terminal controller for a pinned bottom footer.

`ScreenController` owns the terminal: it reserves the bottom ``footer_rows`` with
a DECSTBM scroll region (``ESC[top;bottom r``), prints the run timeline into the
region *above* the footer (where it scrolls into the terminal's native scrollback
exactly as plain output would), and repaints the footer in place at the bottom.

Two properties make it scroll- and resize-safe by construction:

  * **Single writer.** A lone render thread is the only thing that writes to the
    terminal. Callers (the dashboard's event handlers and its spinner ticker)
    only mutate in-memory state via `print_block` / `set_footer`; the render
    thread drains it. There is no second writer to race, so no interleaving and
    no duplicated footer.
  * **No cursor round-trips.** Because the controller is the sole writer it
    always knows the cursor is parked at the bottom of the scroll region — it
    never queries the terminal for the cursor position (the stdin round-trip that
    makes progress-bar libraries stack their footer on resize over SSH). Resize
    is handled by re-reading the size and re-emitting the scroll region; the
    footer is cleared and redrawn exactly once.

The controller is renderer-agnostic: it writes pre-rendered ANSI strings. The
dashboard renders Rich into those strings, so styling lives there and terminal
control lives here. `blessed` is used only for portable capability strings and
size (``term.csr``/``term.move``/``term.clear_eol``/``term.height``)."""

import signal
import threading
from collections import deque
from typing import Callable, List, Optional

import blessed

# DECSC / DECRC — save and restore the cursor position. Universally supported
# (xterm, screen, tmux); used to bracket the footer repaint so the render
# thread's parked cursor is preserved.
_SAVE = "\x1b7"
_RESTORE = "\x1b8"


class ScreenController:
    """Owns the terminal: a scroll region above a pinned footer, driven by a
    single render thread. Thread-safe `print_block` / `set_footer` feed it."""

    def __init__(self, stream, footer_rows: int,
                 on_resize: Optional[Callable[[], None]] = None):
        self._stream = stream
        self._footer_rows = max(1, footer_rows)
        self._on_resize = on_resize
        self.term = blessed.Terminal(stream=stream, force_styling=True)

        self._lock = threading.Lock()
        self._blocks: deque = deque()        # queued timeline blocks (lists of lines)
        self._footer_lines: List[str] = []   # current footer, top→bottom
        self._footer_dirty = False

        # How many rows of the scroll region the timeline currently fills from
        # the top. While below the region height, new lines fill downward; once
        # full, new lines scroll in at the bottom and the line leaving the top is
        # committed to native scrollback. On resize we re-pin the footer but leave
        # the timeline to the terminal's own reflow — repainting it would re-emit
        # already-scrolled lines and duplicate them into scrollback.
        self._visible_count = 0

        self._height = 24
        self._width = 80

        self._wake = threading.Event()       # render thread wakeup
        self._stop = threading.Event()
        self._resize = threading.Event()     # set by the SIGWINCH handler
        self._thread: Optional[threading.Thread] = None
        self._sigwinch_orig = None

    # ---- geometry ------------------------------------------------------------

    def _measure(self) -> None:
        """Refresh cached terminal size. blessed reads the size fresh from the
        stream's tty on each access, so this picks up a resize."""
        self._height = self.term.height or 24
        self._width = self.term.width or 80

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def _scroll_rows(self) -> int:
        """Number of rows above the footer (the scrollable region), ≥ 1."""
        return max(1, self._height - self._footer_rows)

    def _scroll_bottom(self) -> int:
        """0-based index of the bottom row of the scroll region (where new
        timeline lines are written once it is full)."""
        return self._scroll_rows() - 1

    def _park_row(self) -> int:
        """Row to rest the cursor on between frames: just below the last timeline
        line, not the region bottom. A terminal that drops rows around the cursor
        on resize then keeps the content and discards the blank gap beneath it,
        instead of scrolling the content off the top."""
        return min(self._visible_count, self._scroll_bottom())

    # ---- public API (called from any thread; never writes the terminal) ------

    def print_block(self, lines: List[str]) -> None:
        """Queue a block of pre-rendered lines to scroll into the region above
        the footer."""
        if not lines:
            return
        with self._lock:
            self._blocks.append(list(lines))
        self._wake.set()

    def set_footer(self, lines: List[str]) -> None:
        """Replace the pinned footer with `footer_rows` pre-rendered lines."""
        with self._lock:
            self._footer_lines = list(lines)
            self._footer_dirty = True
        self._wake.set()

    # ---- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self._measure()
        self._install_signal()
        self._emit_start()
        self._thread = threading.Thread(
            target=self._run, name="patchwise-ui-render", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._restore_signal()
        self._emit_stop()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(0.1)
            self._wake.clear()
            self._drain_and_render()
        # Final drain so nothing queued just before stop is lost.
        self._drain_and_render()

    # ---- signal --------------------------------------------------------------

    def _install_signal(self) -> None:
        if not hasattr(signal, "SIGWINCH"):
            return
        if threading.current_thread() is not threading.main_thread():
            return
        self._sigwinch_orig = signal.getsignal(signal.SIGWINCH)
        signal.signal(signal.SIGWINCH, self._on_sigwinch)

    def _restore_signal(self) -> None:
        if self._sigwinch_orig is None:
            return
        if threading.current_thread() is not threading.main_thread():
            return
        signal.signal(signal.SIGWINCH, self._sigwinch_orig)
        self._sigwinch_orig = None

    def _on_sigwinch(self, *_args) -> None:
        # Only flag the resize; all terminal work happens on the render thread.
        self._resize.set()
        self._wake.set()

    # ---- rendering (render thread only) --------------------------------------

    def _emit_start(self) -> None:
        """Hide the cursor, establish the scroll region, clear the screen for a
        clean slate (the timeline fills from the top), and park at the top of the
        region. The prior shell screen is preserved in native scrollback."""
        out = [
            self.term.hide_cursor or "",
            self.term.csr(0, self._scroll_bottom()),
            self.term.move(0, 0),
            self.term.clear_eos or "",                # wipe the whole screen
            self.term.move(0, 0),
        ]
        self._write("".join(out))

    def _emit_stop(self) -> None:
        """Release the scroll region and move below the footer, restoring a
        normal terminal."""
        out = [
            self.term.csr(0, self._height - 1),   # reset region to full screen
            self.term.move(self._height - 1, 0),
            self.term.normal_cursor or "",
            "\r\n",
        ]
        self._write("".join(out))

    def _drain_and_render(self) -> None:
        """One frame: handle a pending resize, scroll queued blocks into the
        region, then repaint the footer if dirty. Written as one batched,
        flushed string so a frame is atomic (no partial-write ghosting)."""
        with self._lock:
            blocks = list(self._blocks)
            self._blocks.clear()
            footer = list(self._footer_lines)
            dirty = self._footer_dirty
            self._footer_dirty = False

        out: List[str] = []

        if self._resize.is_set():
            self._resize.clear()
            old_first = self._scroll_rows()   # old footer's first row (0-based)
            self._measure()
            new_first = self._scroll_rows()
            # Re-establish the scroll region at the new size, then clear from the
            # topmost footer row (old or new) down to the bottom. That wipes any
            # stale footer the resize left inside the new region while leaving the
            # timeline above it untouched: the timeline lives in the terminal's
            # own reflow/scrollback, so we never repaint it. Repainting would
            # re-emit lines the terminal already archived on resize and duplicate
            # them into scrollback.
            out.append(self.term.csr(0, self._scroll_bottom()))
            for row in range(min(old_first, new_first), self._height):
                out.append(self.term.move(row, 0))
                out.append(self.term.clear_eol or "")
            # A shrink can leave the fill count past the new region bottom; clamp
            # it so further output appends in-bounds (scrolling at the bottom).
            self._visible_count = min(self._visible_count, self._scroll_rows())
            out.append(self.term.move(self._park_row(), 0))   # rest below content
            if self._on_resize is not None:
                # Let the dashboard re-render the footer at the new width.
                self._on_resize()
                with self._lock:
                    footer = list(self._footer_lines)
                    self._footer_dirty = False
            dirty = True

        scroll_bottom = self._scroll_bottom()
        sr = self._scroll_rows()
        if blocks:
            for block in blocks:
                for line in block:
                    if self._visible_count < sr:
                        # Region not full yet: write at the next empty row from
                        # the top (the timeline fills downward toward the footer).
                        out.append(self.term.move(self._visible_count, 0))
                        out.append(self.term.clear_eol or "")
                        out.append(line)
                        self._visible_count += 1
                    else:
                        # Region full: scroll up one row at the bottom — the line
                        # leaving the top is committed to native scrollback —
                        # then write the new line at the bottom.
                        out.append(self.term.move(scroll_bottom, 0))
                        out.append("\n\r")
                        out.append(line)
            dirty = True  # the cursor moved through the region; repaint footer

        if dirty and footer:
            out.append(self.term.move(self._park_row(), 0))
            out.append(_SAVE)
            first = self._scroll_rows()  # 0-based row of the first footer line
            for i, line in enumerate(footer[: self._footer_rows]):
                out.append(self.term.move(first + i, 0))
                out.append(self.term.clear_eol or "")
                out.append(line)
            out.append(_RESTORE)

        if out:
            self._write("".join(out))

    def _write(self, text: str) -> None:
        if not text:
            return
        try:
            self._stream.write(text)
            self._stream.flush()
        except (ValueError, OSError):
            # Stream closed during teardown — nothing left to draw.
            pass
