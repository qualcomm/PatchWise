# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import argparse
import logging
import os

from patchwise import SANDBOX_PATH

LOG_PATH = os.path.join(SANDBOX_PATH, f"{__name__.split('.')[0]}.log")

# === Global logging config ===
ENABLE_LOG_COLORS = True  # Set to False to disable colored logs in the stream handler
FILE_HANDLER_LOG_LEVEL = logging.DEBUG  # Default log level for file handler

# ANSI color codes
RESET = "\033[0m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
GRAY = "\033[232m"
BOLD = "\033[1m"


class ColorFormatter(logging.Formatter):
    def format(self, record):
        msg = super().format(record)
        if not ENABLE_LOG_COLORS:
            return msg

        # Color everything up to and including the first ": "
        split_idx = msg.find(": ")
        if split_idx != -1:
            header = msg[: split_idx + 2]
            message = msg[split_idx + 2 :]
        else:
            return msg

        if record.levelno >= logging.ERROR:
            return f"{BOLD}{RED}{header}{message}{RESET}"
        elif record.levelno == logging.WARNING:
            return f"{BOLD}{YELLOW}{header}{message}{RESET}"
        elif record.levelno in (logging.INFO, logging.DEBUG):
            return f"{CYAN}{header}{RESET}{message}"

        else:
            return msg


def setup_logger(log_file: str = LOG_PATH, log_level: str = "INFO"):
    """
    Sets up the logger with the specified log file and log level.
    """
    format = "%(asctime)s %(levelname).1s %(name)s %(filename)s#%(lineno)d: %(message)s"
    file_handler = logging.FileHandler(log_file, mode="w")
    file_handler.setLevel(FILE_HANDLER_LOG_LEVEL)  # Use global default
    file_handler.setFormatter(logging.Formatter(format, datefmt="%H:%M:%S"))
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(ColorFormatter(format, datefmt="%H:%M:%S"))
    # Set stream_handler level based on user input
    stream_handler.setLevel(log_level)
    logging.basicConfig(
        level=logging.ERROR,
        handlers=[file_handler, stream_handler],
    )
    logging.getLogger(__name__.split(".")[0]).setLevel(log_level)


def add_logging_arguments(
    parser_or_group: argparse.ArgumentParser | argparse._ArgumentGroup,
    config: dict
):
    parser_or_group.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default=config["log_level"],
        help="Set the logging level. (default: %(default)s)",
    )
    parser_or_group.add_argument(
        "--log-file",
        default=LOG_PATH,
        help="Path to the log file. (default: %(default)s)",
    )
    return parser_or_group
