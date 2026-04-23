# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os
from pathlib import Path

# Get the path of the patchwise package
PACKAGE_PATH = Path(__file__).resolve().parent

PACKAGE_NAME = __name__.split(".")[0]

# Define the sandbox/workspace path.
# Honor PATCHWISE_SANDBOX_PATH so operators can locate the sandbox to a
# filesystem with enough free space (/tmp may be a small tmpfs).
_default_sandbox = Path("/tmp") / PACKAGE_NAME / "sandbox"
SANDBOX_PATH = Path(os.environ.get("PATCHWISE_SANDBOX_PATH", str(_default_sandbox)))
SANDBOX_BIN = SANDBOX_PATH / "bin"
# Define the kernel workspace path
KERNEL_PATH = SANDBOX_PATH / "kernel"

# Define the output directory path
_default_output = Path("/tmp") / PACKAGE_NAME / "output"
OUTPUT_PATH = Path(os.environ.get("PATCHWISE_OUTPUT_PATH", str(_default_output)))

# Ensure the sandbox directory exists
SANDBOX_PATH.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
