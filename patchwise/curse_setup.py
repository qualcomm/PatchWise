# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import curses
import yaml
from patchwise import PACKAGE_PATH

config_dir = PACKAGE_PATH / "patchwise_config.yaml"



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


def write_agreement_to_yaml(agreement: str, dont_show_again: bool) -> None:
    with config_dir.open("r") as file:
        yaml_dict = yaml.safe_load(file)

    api_config = yaml_dict.get(agreement, {})
    if not api_config.get("key_agreement"):
        api_config["key_agreement"] = True
    if dont_show_again:
        api_config["show_again"] = False
    with config_dir.open("w") as file:
        yaml.dump(yaml_dict, file, default_flow_style=False)


def show_agreement_popup(stdscr):
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
        if key == ord("1"):
            write_agreement_to_yaml("open_ai", dont_show_again=False)
        elif key == ord("3"):
            write_agreement_to_yaml("open_ai", dont_show_again=True)
        terminate_curses(stdscr)
        return False


def check_api_key_agreement(api_name: str) -> tuple[bool, bool]:
    # should check if the key agreement is true as well as if show again is true
    try:
        with config_dir.open("r") as file:
            yaml_dict = yaml.safe_load(file)

        api_config = yaml_dict.get(api_name, {})

        key_agreed = api_config.get("key_agreement")
        show_again = api_config.get("show_again")

        return key_agreed, show_again

    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found at {config_dir}")
    except yaml.YAMLError as e:
        raise ValueError(f"YAML parsing error: {e}")
    except Exception as e:
        raise RuntimeError(
            f"Unexpected error reading API key agreement for {api_name}: {e}"
        )


def curse_pipeline():
    bool_agree, bool_show = check_api_key_agreement("open_ai")
    if (bool_agree is False) or (bool_agree is True and bool_show is True):
        # means key_agreement for open_ai is false, then we should show popup
        stdscr = setup_curses()
        show_agreement_popup(stdscr)
    elif bool_agree is True and bool_show is False:
        # means that we won't popup anything since yaml_dict's key agreement is true
        pass
    else:
        exit(1)
