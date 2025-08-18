# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from unittest.mock import Mock, patch

import pytest
import yaml

from patchwise.utils.tui import display_prompt_with_options

message = "Do you agree?"


@pytest.mark.parametrize(
    "key_pressed,expected_result,options",
    [
        ("1", "Yes", ["Yes", "No", "Yes. Don't show again"]),
        ("2", "No", ["Yes", "No", "Yes. Don't show again"]),
        ("3", "Yes. Don't show again", ["Yes", "No", "Yes. Don't show again"]),
        ("q", "", ["Yes", "No", "Yes. Don't show again"]),
    ],
)
@patch("curses.initscr")  # patch makes temp object for testing
@patch("curses.noecho")
@patch("curses.cbreak")
@patch("curses.nocbreak")
@patch("curses.echo")
@patch("curses.endwin")
@patch("curses.newwin")
def test_display_prompt_with_options(
    mock_newwin,
    mock_endwin,
    mock_echo,
    mock_nocbreak,
    mock_cbreak,
    mock_noecho,
    mock_initscr,
    key_pressed,
    expected_result,
    options,
):
    # using arrange, act, assert, cleanup anatomy

    # arrange
    mock_stdscr = Mock()
    mock_stdscr.getmaxyx.return_value = (24, 80)
    mock_initscr.return_value = mock_stdscr

    mock_win = Mock()
    mock_win.getch.return_value = ord(key_pressed)
    mock_newwin.return_value = mock_win

    # act
    out = display_prompt_with_options(message, options)

    # assert
    assert out == expected_result
    mock_initscr.assert_called_once()
    mock_noecho.assert_called_once()
    mock_cbreak.assert_called_once()

    mock_win.clear.assert_called_once()
    mock_win.box.assert_called_once()
    mock_win.refresh.assert_called_once()


def test_config(tmp_path):
    # arrange
    test_dict = {
        "log_level": "INFO",
        "api_key_disclaimer": {
            "message": "Sample Message",
            "options": ["Yes", "No", "Yes. Don't show again"],
            "no_reprompt": False,
        },
    }

    yaml_file = tmp_path / "test_config.yaml"
    yaml_file.write_text(yaml.dump(test_dict))

    # act
    yaml_dict = yaml.safe_load(yaml_file.read_text())

    # assert
    assert isinstance(yaml_dict, dict)
    assert yaml_dict == test_dict

    assert set(yaml_dict.keys()) == {"log_level", "api_key_disclaimer"}
    assert yaml_dict["log_level"] == "INFO"
