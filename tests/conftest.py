# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--model", default=None, help="--model passed to patchwise AiCodeReview")
    parser.addoption("--provider", default=None, help="--provider passed to patchwise AiCodeReview")
    parser.addoption("--embedding-model", default=None, help="litellm model for embeddings (default: text-embedding-3-small)")
    parser.addoption("--embedding-provider", default=None, help="api_base for litellm embedding calls")
    parser.addoption("--reviews-dir", default=None, help="use existing aicodereview.txt files from this directory instead of running patchwise")
