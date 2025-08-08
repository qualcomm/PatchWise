# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from platformdirs import user_config_dir
from patchwise import PACKAGE_PATH
from pathlib import Path
from typing import Dict, Any, cast
import yaml

CONFIG_DIR = Path(user_config_dir())
DEFAULT_CONFIG_PATH = PACKAGE_PATH / "default_config.yaml"
USER_CONFIG_PATH = CONFIG_DIR / "patchwise_config.yaml"


def read_from_config(path: Path) -> Dict[str, Any]:
    with open(path, "r") as file:
        config_dict = yaml.safe_load(file)

    if config_dict is None:
        return {}

    if not isinstance(config_dict, dict):
        raise ValueError(f"Config must be a dictionary, got {type(config_dict)}")

    return cast(Dict[str, Any], config_dict)


def parse_config() -> Dict[str, Any]:
    """
    Parses both user and default configuration files and returns the union of the two with user taking precedence.
    """
    default_options = read_from_config(DEFAULT_CONFIG_PATH)
    try:
        user_options = read_from_config(USER_CONFIG_PATH)
    except FileNotFoundError:
        user_options: Dict[str, Any] = {}

    if not user_options:
        return default_options

    combined_options = {
        **default_options,
        **{k: v for k, v in user_options.items() if v is not None},
    }

    return combined_options
