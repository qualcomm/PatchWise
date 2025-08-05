# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from pathlib import Path
from platformdirs import user_config_dir

# Get the path of the patchwise package
PACKAGE_PATH = Path(__file__).resolve().parent

PACKAGE_NAME = __name__.split(".")[0]

# Define the sandbox/workspace path in tmp directory
SANDBOX_PATH = Path("/tmp") / PACKAGE_NAME / "sandbox"
SANDBOX_BIN = SANDBOX_PATH / "bin"
# Define the kernel workspace path
KERNEL_PATH = SANDBOX_PATH / "kernel"

# Ensure the sandbox directory exists
SANDBOX_PATH.mkdir(parents=True, exist_ok=True)

CONFIG_PATH = Path(user_config_dir())
CONFIG_PATH.mkdir(parents=True, exist_ok=True)