# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import curses
import textwrap


def display_prompt_with_options(message: str, options: list[str]) -> str:
    stdscr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)

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
        curses.nocbreak()
        stdscr.keypad(False)
        curses.echo()
        curses.endwin()
