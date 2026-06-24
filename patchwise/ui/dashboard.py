# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""A live terminal dashboard for a patchwise run.

The display has two parts:

  * A **scrollback timeline** — the run is printed as permanent lines, grouped
    into phase sections (``─ PLAN ─``, ``─ EXECUTE ─``, … for review;
    ``─ RCA · engineer/maintainer ─`` for crashdump RCA), rendered with Rich.
  * A **pinned status footer** at the bottom — a phase strip, iteration, token
    meter, elapsed timer, and the current tool call.

Both are driven through `ScreenController` (`screen.py`), which reserves the
bottom rows with a terminal scroll region (DECSTBM). The timeline scrolls in the
region *above* the footer, so it lands in native scrollback (tmux/screen copy
mode, mouse wheel, Shift-PgUp) while the footer never does — it is repainted in
place and re-established on resize by a single render thread, so it can neither
leak into scrollback nor stack on resize.

`Dashboard` translates the `events` bus into Rich renderables, renders them to
ANSI strings, and hands those to the controller; the pipeline stays UI-agnostic
and only calls `events.emit(...)`. Use it via `live_dashboard(args)` in `main()`.

Colour is semantic and limited: green = keep/accept/pass, red = drop/fail,
yellow = needs-attention (refute / material change / warning), cyan =
active/in-progress, dim = structure/done. Every coloured state also has a glyph
(✓ ✗ · ? →), so colour is never load-bearing alone."""

import io
import logging
import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from patchwise import SANDBOX_PATH
from patchwise.ui import events
from patchwise.ui.screen import ScreenController

# Braille spinner frames (plain Unicode, not emoji).
_SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# The pinned footer is rendered with Rich (so the active phase can be highlighted
# and colours stay semantic) into N reserved rows: a labelled top divider that
# sets the footer apart from the scrolling timeline, _ACT_ROWS activity rows, an
# inner divider, and the status line.
_ACT_ROWS = 5
_FOOTER_ROWS = _ACT_ROWS + 3

# Phase strips per pipeline: ordered (key, label) the footer phase strip walks.
_PHASES = {
    "review": [("plan", "plan"), ("critique", "critique"),
               ("execute", "execute"), ("filter", "filter")],
    "rca": [("engineer", "engineer"), ("maintainer", "maintainer")],
}


def _phase_key(label: str) -> str:
    """Map an agent loop label (e.g. 'critic:r2', 'exec:merged', 'maintainer:r1')
    to the phase-strip key it belongs to."""
    lbl = (label or "").lower()
    if lbl.startswith("plan"):
        return "plan"
    if lbl.startswith("critic"):
        return "critique"
    if lbl.startswith("exec"):
        return "execute"
    if lbl.startswith(("fp-filter", "filter", "cleanup")):
        return "filter"
    if lbl.startswith("engineer"):
        return "engineer"
    if lbl.startswith("maintainer"):
        return "maintainer"
    return lbl


def _oneline(text: str, width: Optional[int] = None) -> str:
    """First non-empty line of `text`, stripped; truncated to `width` with an
    ellipsis only when a width is given (callers that crop to the screen pass
    none)."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            if width is None or len(line) <= width:
                return line
            return line[: width - 1] + "…"
    return ""


def _short_args(name: str, args: Dict[str, Any]) -> str:
    """A one-line summary of a tool call's arguments for the activity footer,
    returned in full — the footer row crops it to the screen width."""
    if not isinstance(args, dict) or not args:
        return ""
    for key in ("pattern", "path", "name", "symbol", "subsystem_file", "url", "query"):
        if args.get(key):
            return _oneline(str(args[key]))
    first = next(iter(args.values()))
    return _oneline(str(first))


class Dashboard:
    """Event-bus translator: prints the run as a Rich timeline above a pinned
    status footer, both routed through a `ScreenController`."""

    def __init__(self, console: Console,
                 controller: Optional[ScreenController] = None,
                 output_dir: Optional[str] = None):
        self._lock = threading.Lock()
        self._console = console        # used only as a Rich → string renderer
        self._controller = controller
        self._start = time.monotonic()
        self._spin = 0
        self.output_dir = output_dir

        # Footer state.
        self.pipeline: Optional[str] = None
        self.target = ""
        self.model = ""
        self.label = ""
        self.phase = ""
        self.iter_n = 0
        self.iter_cap = 0
        self.tokens = 0
        self.budget = 0
        self._status_override: Optional[str] = None
        self.tool_calls: deque = deque(maxlen=_ACT_ROWS)

        # Timeline / summary state.
        self._cur_section: Optional[str] = None
        self.plan_units = 0
        self.critic_rounds = 0
        self.findings = 0
        self.kept = 0
        self.dropped = 0
        self.maintainer_rounds = 0
        self._finding_rows: List[Tuple[int, str, str]] = []
        self._last_engineer = ""
        self._accepted_printed = False
        self.done_summary: Optional[Dict[str, Any]] = None

    # ---- Rich → ANSI strings -------------------------------------------------

    def _render(self, renderable: Any, width: Optional[int] = None) -> List[str]:
        """Render a Rich renderable to a list of ANSI lines at the current
        terminal width. The controller writes these strings; Rich never touches
        the terminal itself."""
        if width is None:
            width = self._controller.width if self._controller else self._console.width
        cap = Console(file=io.StringIO(), width=max(width, 1), force_terminal=True,
                      no_color=self._console.no_color)
        with cap.capture() as c:
            cap.print(renderable, end="")
        return c.get().split("\n")

    # ---- footer (pinned bottom) ----------------------------------------------

    def _elapsed(self) -> str:
        secs = int(time.monotonic() - self._start)
        return f"{secs // 60:d}:{secs % 60:02d}"

    def _status_grid(self):
        """Phase strip (active phase highlighted reverse-cyan, done dim-green ✓,
        pending dim) on the left; iter / token meter / elapsed on the right."""
        strip = _PHASES.get(self.pipeline or "", [])
        active = self.phase or _phase_key(self.label)
        order = [k for k, _ in strip]
        active_idx = order.index(active) if active in order else -1
        chips = Text(no_wrap=True, overflow="crop")
        for i, (key, label) in enumerate(strip):
            if i:
                chips.append(" → ", style="dim")
            if i < active_idx:                       # done
                chips.append("✓ ", style="green")
                chips.append(label, style="dim")
            elif i == active_idx:                    # active — highlighted
                chips.append(f" {label} ", style="bold reverse cyan")
            else:                                    # pending
                chips.append(label, style="dim")

        right = Text(no_wrap=True, overflow="crop")
        if self.iter_cap:
            right.append(f"iter {self.iter_n}/{self.iter_cap}   ", style="dim")
        if self.budget:
            near = self.tokens >= 0.8 * self.budget
            right.append(f"{self.tokens // 1000}k/{self.budget // 1000}k tok   ",
                         style="yellow" if near else "dim")
        elif self.tokens:
            right.append(f"{self.tokens // 1000}k tok   ", style="dim")
        right.append(self._elapsed(), style="dim")

        bar = Table.grid(expand=True)
        bar.add_column(justify="left", ratio=1, no_wrap=True, overflow="crop")
        bar.add_column(justify="right", no_wrap=True)
        bar.add_row(chips, right)
        return bar

    def _activity_grid(self):
        """Up to _ACT_ROWS recent tool calls (or a pinned 'cleaning up…'), led by
        the spinner on the first row; a fixed row count keeps the footer height
        constant."""
        rows: List[Any] = []
        if self._status_override:
            rows.append(Text(self._status_override, style="dim italic",
                             no_wrap=True, overflow="crop"))
        else:
            for tc in list(self.tool_calls)[-_ACT_ROWS:]:
                ok = "✓" if tc.get("ok") else "✗"
                ok_style = "green" if tc.get("ok") else "red"
                summary = _short_args(tc.get("name", ""), tc.get("args") or {})
                rows.append(Text.assemble(
                    (ok + " ", ok_style),
                    (f"{tc.get('name','')}", "cyan"),
                    (f"  {summary}" if summary else "", "dim"),
                    no_wrap=True, overflow="crop"))
            if not rows:
                rows.append(Text("starting…", style="dim italic",
                                 no_wrap=True, overflow="crop"))
        while len(rows) < _ACT_ROWS:
            rows.append(Text("", no_wrap=True, overflow="crop"))

        # Expand to the full width with a fixed 2-cell spinner gutter, so a long
        # tool-call arg fills the row and crops cleanly on the right (the spinner
        # stays put) rather than the row clipping from the left.
        grid = Table.grid(expand=True)
        grid.add_column(no_wrap=True, width=2)
        grid.add_column(ratio=1, no_wrap=True, overflow="crop")
        spin = Text(_SPIN[self._spin % len(_SPIN)] + " ", style="cyan")
        for i, r in enumerate(rows):
            grid.add_row(spin if i == 0 else Text("  "), r)
        return grid

    def _footer_lines(self, width: int) -> List[str]:
        """Render the footer (activity rows + divider + status line) to exactly
        _FOOTER_ROWS ANSI strings, one per reserved row."""
        header = Rule(Text(" activity ", style="dim"), align="left",
                      characters="─", style="grey37")
        group = Group(header, self._activity_grid(),
                      Rule(style="grey37"), self._status_grid())
        lines = self._render(group, width=width)
        return (lines + [""] * _FOOTER_ROWS)[:_FOOTER_ROWS]

    def update_footer(self) -> None:
        """Recompute the footer lines and hand them to the controller (which
        repaints them in its render thread). Safe to call from the ticker thread:
        it only renders strings and stores them — it never writes the terminal."""
        if self._controller is None:
            return
        self._controller.set_footer(self._footer_lines(self._controller.width))

    def tick(self) -> None:
        """Advance the spinner and refresh the footer (called by the ticker)."""
        self._spin += 1
        self.update_footer()

    def set_status(self, text: Optional[str]) -> None:
        """Pin a fixed line in the activity row (e.g. 'cleaning up…' on Ctrl-C)."""
        with self._lock:
            self._status_override = text
        self.update_footer()

    def begin_cleanup(self) -> None:
        """Ctrl-C: show 'cleaning up…' in the footer. The footer lives in the
        reserved scroll region, so it stays put while teardown runs."""
        self.set_status("cleaning up…")

    # ---- timeline (printed above the footer, scrolls natively) ---------------

    def _print(self, renderable: Any = None) -> None:
        if self._controller is None:
            return
        if renderable is None:
            self._controller.print_block([""])
        else:
            self._controller.print_block(self._render(renderable))

    def _section(self, name: str) -> None:
        if self._cur_section == name:
            return
        self._cur_section = name
        label = Text(f" {name} ", style="bold")
        self._print()
        self._print(Rule(label, align="left", characters="─", style="dim"))

    def _emit(self, renderable: Any, indent: int = 2) -> None:
        self._print(Padding(renderable, (0, 0, 0, indent)))

    def _plan_body(self, tasks: List[Dict[str, Any]]) -> Any:
        t = Table.grid(padding=(0, 2))
        t.add_column(style="bold", no_wrap=True)
        t.add_column(no_wrap=True)
        t.add_column(ratio=1)
        for task in tasks:
            n = len(task.get("files") or [])
            s = len(task.get("symbols") or [])
            meta = f"  ({n}f/{s}s)" if (n or s) else ""
            t.add_row(str(task.get("id", "")),
                      _oneline(task.get("dimension", ""), 16),
                      Text.assemble((_oneline(task.get("focus", ""), 76), "default"),
                                    (meta, "dim")))
        return t

    def _print_accepted(self, text: str) -> None:
        """Print the accepted root cause — the only bordered block in a run."""
        if not text:
            return
        self._accepted_printed = True
        self._print()
        self._print(Panel(
            Markdown(text),
            title=Text("accepted root cause", style="bold green"),
            title_align="left", border_style="green", padding=(0, 1)))

    # ---- event ingestion -----------------------------------------------------

    def on_event(self, kind: str, f: Dict[str, Any]) -> None:
        if kind == events.RUN_START:
            with self._lock:
                self.pipeline = f.get("pipeline")
                self.target = f.get("target", "") or ""
                self.model = f.get("model", "") or ""
            kind_label = "crashdump RCA" if self.pipeline == "rca" else "patch review"
            self._print(Rule(
                Text.assemble(("patchwise · ", "bold cyan"), (kind_label, "cyan")),
                align="left", style="cyan"))
            meta = Table.grid(padding=(0, 2))
            meta.add_column(style="bold dim", no_wrap=True)
            meta.add_column(overflow="fold")
            if self.target:
                meta.add_row("target", self.target)
            if self.model:
                meta.add_row("model", self.model)
            self._emit(meta, indent=3)

        elif kind == events.PHASE:
            with self._lock:
                self.phase = f.get("name", "") or self.phase

        elif kind == events.ITERATION:
            with self._lock:
                self.label = f.get("label", "") or self.label
                self.iter_n = f.get("n", 0)
                self.iter_cap = f.get("cap", 0)
                self.tokens = f.get("tokens", self.tokens) or self.tokens
                self.budget = f.get("budget", self.budget) or self.budget

        elif kind == events.TOOL_CALL:
            with self._lock:
                self.label = f.get("label", "") or self.label
                self.tool_calls.append(f)

        elif kind == events.PLAN:
            tasks = list(f.get("tasks") or [])
            with self._lock:
                self.plan_units = len(tasks)
            if tasks:
                self._section("PLAN")
                self._emit(self._plan_body(tasks))

        elif kind == events.CRITIC:
            with self._lock:
                self.critic_rounds += 1
            self._section("CRITIQUE")
            n = f.get("round", "?")
            if f.get("material"):
                self._emit(Text.assemble((f"r{n}  ", "dim"),
                                         ("· material change", "yellow")))
            else:
                self._emit(Text.assemble((f"r{n}  ", "dim"),
                                         ("✓ no change — plan stands", "green")))
            for fb in (f.get("feedback") or []):
                self._emit(Text((fb or "").strip(), style="dim"), indent=6)

        elif kind == events.FINDING:
            with self._lock:
                self.findings += 1
                n = self.findings
            loc = f.get("location") or ""
            dim = f.get("dimension") or ""
            text = (f.get("text", "") or "").strip()
            self._finding_rows.append((n, loc, text))
            self._section("EXECUTE")
            self._print()  # separate consecutive findings with a blank line
            self._emit(Text.assemble((f"#{n}  ", "bold red"),
                                     (f"[{dim}] " if dim else "", "dim"),
                                     (loc, "cyan")))
            self._emit(Text(text, style="default"), indent=6)

        elif kind == events.VERDICT:
            drop = f.get("verdict") == "drop"
            with self._lock:
                if drop:
                    self.dropped += 1
                else:
                    self.kept += 1
            self._section("FILTER")
            finding = (f.get("finding", "") or "").strip()
            reason = (f.get("reason", "") or "").strip()
            if drop:
                self._emit(Text.assemble(("· drop  ", "dim"), (finding, "dim"),
                                         (f"   {reason}" if reason else "", "dim")))
            else:
                self._emit(Text.assemble(("✓ keep  ", "green"), (finding, "default"),
                                         (f"   {reason}" if reason else "", "dim")))

        elif kind == events.ENGINEER_ANSWER:
            text = (f.get("text", "") or "").strip()
            if text and text != self._last_engineer:
                self._last_engineer = text
                self._section("RCA · engineer")
                self._emit(Markdown(text))

        elif kind == events.MAINTAINER:
            with self._lock:
                self.maintainer_rounds += 1
            n = f.get("round", "?")
            self._section(f"RCA · maintainer · r{n}")
            if f.get("refuted"):
                reason = (f.get("reason", "") or "").strip()
                self._emit(Text.assemble(("· refuted", "yellow"),
                                         (f" — {reason}" if reason else "", "dim")))
                for q in (f.get("questions") or []):
                    self._emit(Text.assemble(("? ", "yellow"),
                                             ((q or "").strip(), "default")))
            else:
                self._emit(Text("✓ accepted", style="green"))
                self._print_accepted(self._last_engineer)

        elif kind == events.RUN_DONE:
            with self._lock:
                self.done_summary = f.get("summary") or {}
            if (self.pipeline == "rca" and not self._accepted_printed
                    and self._last_engineer):
                self._print_accepted(self._last_engineer)

        self.update_footer()

    def add_alert(self, level: str, message: str) -> None:
        style = "bold red" if level in ("ERROR", "CRITICAL") else "bold yellow"
        self._print(Text(f"! {level}: {(message or '').strip()}", style=style))

    # ---- final summary -------------------------------------------------------

    def summary_panel(self) -> Panel:
        s = self.done_summary or {}
        tok = f"{self.tokens:,}" + (f" / {self.budget:,}" if self.budget else "")

        meta = Table.grid(padding=(0, 2))
        meta.add_column(style="bold dim", no_wrap=True)
        meta.add_column(overflow="fold")
        meta.add_row("target", self.target or "-")
        meta.add_row("model", self.model or "-")
        meta.add_row("elapsed", f"{self._elapsed()}    tokens {tok}")
        if self.pipeline == "rca":
            meta.add_row("rca", f"{self.maintainer_rounds} maintainer round(s)")
        else:
            meta.add_row("plan", f"{self.plan_units} units, {self.critic_rounds} critic round(s)")

        body: List[Any] = [meta]
        if self.pipeline != "rca" and self._finding_rows:
            reported = len(self._finding_rows)
            issues = s.get("issues")
            head = Text.assemble(
                ("findings  ", "bold"),
                (f"{reported} reported", "default"),
                (f", {self.dropped} filtered" if self.dropped else "", "dim"),
                (f"   ({issues} in result)" if issues is not None else "", "dim"))
            body += [Text(), head]
            for (n, loc, text) in self._finding_rows:
                body.append(Text.assemble(
                    (f"  #{n} ", "bold"), (f"{loc}  " if loc else "", "cyan"),
                    (_oneline(text, 58), "default"),
                    no_wrap=True, overflow="crop"))

        out = str(self.output_dir or SANDBOX_PATH)
        body += [Text(), Text.assemble(("output  ", "bold dim"), (out, "dim"))]
        return Panel(Group(*body), title=Text("run complete", style="bold green"),
                     title_align="left", border_style="green", padding=(1, 2))


class _AlertHandler(logging.Handler):
    """Funnels WARNING+ log records into the timeline, so the user is never blind
    to backoffs/errors even though the INFO stream is hidden."""

    def __init__(self, dashboard: Dashboard):
        super().__init__(level=logging.WARNING)
        self._dashboard = dashboard

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._dashboard.add_alert(record.levelname, record.getMessage())
        except Exception:
            pass


@contextmanager
def live_dashboard(args: Any):
    """Run the live dashboard around a review/rca dispatch.

    Detaches the stderr INFO log handler (keeping the file handler), prints the
    run as a Rich timeline above a pinned status footer via a `ScreenController`,
    animates the footer with a ticker thread, and on exit stops the controller
    (which restores the terminal) and prints a static summary."""
    output_dir = getattr(args, "output_dir", None)
    console = Console(stderr=True, no_color=bool(os.environ.get("NO_COLOR")))

    dashboard = Dashboard(console, output_dir=output_dir)
    # The controller owns the terminal. on_resize lets it ask the dashboard to
    # re-render the footer at the new width as part of a single resize frame.
    controller = ScreenController(console.file, _FOOTER_ROWS,
                                  on_resize=dashboard.update_footer)
    dashboard._controller = controller

    # Detach the stderr stream handler (FileHandler is a StreamHandler subclass,
    # so exclude it) and route WARNING+ into the timeline instead.
    root = logging.getLogger()
    detached = [
        h for h in list(root.handlers)
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
    ]
    alert_handler = _AlertHandler(dashboard)
    for h in detached:
        root.removeHandler(h)
    root.addHandler(alert_handler)

    controller.start()
    dashboard.update_footer()
    events.subscribe(dashboard.on_event)

    # Animate the spinner / tick the timer during event-less pauses. The ticker
    # only mutates state and re-renders the footer strings; the controller's
    # render thread is the sole terminal writer, so there is no write race.
    stop_tick = threading.Event()

    def _ticker():
        while not stop_tick.wait(0.4):
            dashboard.tick()

    ticker = threading.Thread(target=_ticker, name="patchwise-ui-tick", daemon=True)
    ticker.start()

    try:
        yield dashboard
    finally:
        stop_tick.set()
        ticker.join(timeout=1)
        events.unsubscribe(dashboard.on_event)
        root.removeHandler(alert_handler)
        for h in detached:
            root.addHandler(h)
        controller.stop()   # restores the scroll region and shows the cursor
        console.print(dashboard.summary_panel())
