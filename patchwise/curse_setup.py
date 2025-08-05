# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import curses
import yaml
from patchwise import CONFIG_PATH

config_file = CONFIG_PATH / "patchwise_config.yaml"


def setup_curses():
    stdscr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
    return stdscr


def terminate_curses(stdscr) -> None:
    curses.nocbreak()
    stdscr.keypad(False)
    curses.echo()
    curses.endwin()


def show_agreement_popup(stdscr, yaml_dict):
    # this should only occur if open ai key is not in ENV
    agreement_text = [
        "PatchWise uses LiteLLM. Your API key will be",
        "used from your environment to make an",
        "API request to your specified provider.",
        "Default: OPENAI_API_KEY",
        "",
        "Do you acknowledge?",
        "1. Yes",
        "2. No",
        "3. Yes and don't show again",
    ]
    (y, x) = stdscr.getmaxyx()

    height = len(agreement_text) + 4
    width = max(len(line) for line in agreement_text) + 4

    start_y = (y - height) // 2
    start_x = (x - width) // 2

    popup_win = curses.newwin(height, width, start_y, start_x)
    popup_win.box()

    for idx, line in enumerate(agreement_text, start=2):
        popup_win.addstr(idx, 2, line)

    popup_win.refresh()
    while True:
        key = popup_win.getch()
        if key == ord("2"):
            exit(1)
        elif key == ord("3"):
            yaml_dict["show_key_disclaimer"] = False
            write_yaml(yaml_dict)
        terminate_curses(stdscr)
        return False


def read_yaml() -> dict:
    with config_file.open("r") as file:
        yaml_dict = yaml.safe_load(file)
        file.close()
    return yaml_dict


def write_yaml(yaml_dict) -> None:
    with config_file.open("w") as file:
        yaml.dump(yaml_dict, file)
        file.close()


def show_again() -> bool:
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    try:
        yaml_dict = read_yaml()
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Failed to parse YAML: {e}")

    return yaml_dict["show_key_disclaimer"]


def curse_pipeline():
    # if config doesn't exist, we need to make one

    # need to check if file exists
    if not config_file.exists():
        data = {"show_key_disclaimer": True}
        write_yaml(data)
    yaml_dict = read_yaml()

    if yaml_dict["show_key_disclaimer"] == True:
        stdscr = setup_curses()
        show_agreement_popup(stdscr, yaml_dict)
    pass
