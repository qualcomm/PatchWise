# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Validation of the optional severity setting after configuration merging."""

import pytest
import yaml

from patchwise.utils import config


@pytest.fixture
def user_config(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "USER_CONFIG_PATH", path)
    return path


@pytest.mark.parametrize(
    "contents",
    [
        None,
        "",
        "ai: {}\n",
        "ai:\n  code_review: {}\n",
        "ai:\n  code_review: null\n",
        "ai:\n  code_review:\n    output_severity: null\n",
    ],
)
def test_ai_output_severity_defaults_to_false(user_config, contents):
    if contents is not None:
        user_config.write_text(contents)
    assert config.ai_output_severity() is False


@pytest.mark.parametrize("setting", [False, True])
def test_ai_output_severity_accepts_booleans(user_config, setting):
    user_config.write_text(
        yaml.safe_dump({"ai": {"code_review": {"output_severity": setting}}})
    )
    assert config.ai_output_severity() is setting


@pytest.mark.parametrize(
    "setting",
    ["true", "false", "", 0, 1, -1, 0.0, 1.0, [], {}, [True], {"value": True}],
)
def test_ai_output_severity_rejects_non_booleans(user_config, setting):
    user_config.write_text(
        yaml.safe_dump({"ai": {"code_review": {"output_severity": setting}}})
    )
    with pytest.raises(
        ValueError, match=r"ai\.code_review\.output_severity must be true or false"
    ):
        config.ai_output_severity()


@pytest.mark.parametrize(
    "code_review", [False, True, "false", "invalid", 0, 1, 0.0, [], ["output_severity"]]
)
def test_ai_output_severity_rejects_non_dictionary_blocks(user_config, code_review):
    user_config.write_text(yaml.safe_dump({"ai": {"code_review": code_review}}))
    with pytest.raises(ValueError, match=r"ai\.code_review must be a dictionary"):
        config.ai_output_severity()


@pytest.mark.parametrize("ai", [{}, {"code_review": {}}])
def test_ai_output_severity_handles_older_defaults(
    user_config, tmp_path, monkeypatch, ai
):
    defaults = tmp_path / "defaults.yaml"
    defaults.write_text(yaml.safe_dump({"ai": ai}))
    monkeypatch.setattr(config, "DEFAULT_CONFIG_PATH", defaults)
    assert config.ai_output_severity() is False
