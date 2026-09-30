# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import contextlib
import curses
import sys
import textwrap

_TUI_SETUP_ERROR = (
    "PatchWise needs an interactive terminal to complete the first-run setup. "
    "Run PatchWise once in a normal terminal to confirm the API key disclaimer. "
    "If you are running it headlessly, set no_reprompt to true under "
    "api_key_disclaimer in ~/.config/patchwise_config.yaml:\n"
    "api_key_disclaimer:\n"
    "  no_reprompt: true"
)


def _restore_terminal(stdscr) -> None:
    with contextlib.suppress(curses.error):
        curses.nocbreak()
    if stdscr is not None:
        with contextlib.suppress(curses.error):
            stdscr.keypad(False)
    with contextlib.suppress(curses.error):
        curses.echo()
    with contextlib.suppress(curses.error):
        curses.endwin()


def display_prompt_with_options(message: str, options: list[str]) -> str:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SystemExit(_TUI_SETUP_ERROR)

    stdscr = None
    try:
        stdscr = curses.initscr()
        curses.noecho()
        curses.cbreak()
        stdscr.keypad(True)
    except curses.error:
        _restore_terminal(stdscr)
        raise SystemExit(_TUI_SETUP_ERROR) from None

    try:
        (y, x) = stdscr.getmaxyx()
        wrap_width = min(x - 6, 80)
        wrapped_message = textwrap.wrap(message, wrap_width)

        height = len(wrapped_message) + len(options) + 4
        width = (
            max(
                max(len(line) for line in wrapped_message),
                max(len(f"{i}. {opt}") for i, opt in enumerate(options, 1)),
            )
            + 4
        )

        start_y = (y - height) // 2
        start_x = (x - width) // 2

        win = curses.newwin(height, width, start_y, start_x)
        win.clear()
        win.box()

        for i, line in enumerate(wrapped_message, start=1):
            win.addstr(i, 2, line)

        for idx, option in enumerate(options, start=1):
            win.addstr(len(wrapped_message) + idx + 1, 2, f"{idx}. {option}")

        win.refresh()

        while True:
            key = win.getch()
            if ord("1") <= key <= ord(str(len(options))):
                return options[key - ord("1")]
            elif key == ord("q"):
                return ""
    finally:
        _restore_terminal(stdscr)
