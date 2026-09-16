# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import yaml

from patchwise.utils import config


def _patch_paths(monkeypatch, tmp_path):
    default_path = tmp_path / "default_config.yaml"
    default_path.write_text(
        yaml.dump(
            {
                "log_level": "INFO",
                "mail": {"imap": {"server": "imap.example.com", "ssl": True}},
            }
        )
    )
    config_dir = tmp_path / "config_dir"
    user_path = config_dir / "patchwise_config.yaml"

    monkeypatch.setattr(config, "DEFAULT_CONFIG_PATH", default_path)
    monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config, "USER_CONFIG_PATH", user_path)
    return default_path, user_path


def test_update_user_config_seeds_from_defaults_on_first_write(monkeypatch, tmp_path):
    default_path, user_path = _patch_paths(monkeypatch, tmp_path)

    assert not user_path.exists()

    config.update_user_config(("log_level",), "DEBUG")

    assert user_path.exists()
    written = yaml.safe_load(user_path.read_text())
    assert written["log_level"] == "DEBUG"
    # Everything else from the seeded default copy is preserved.
    assert written["mail"]["imap"]["server"] == "imap.example.com"


def test_update_user_config_creates_nested_keys(monkeypatch, tmp_path):
    default_path, user_path = _patch_paths(monkeypatch, tmp_path)

    config.update_user_config(("mail", "imap", "ssl"), False)

    written = yaml.safe_load(user_path.read_text())
    assert written["mail"]["imap"]["ssl"] is False
    assert written["mail"]["imap"]["server"] == "imap.example.com"


def test_update_user_config_leaves_unrelated_keys_untouched(monkeypatch, tmp_path):
    default_path, user_path = _patch_paths(monkeypatch, tmp_path)

    config.update_user_config(("log_level",), "DEBUG")
    config.update_user_config(("mail", "imap", "server"), "custom.example.com")

    written = yaml.safe_load(user_path.read_text())
    assert written["log_level"] == "DEBUG"
    assert written["mail"]["imap"]["server"] == "custom.example.com"
    assert written["mail"]["imap"]["ssl"] is True


def test_update_user_config_does_not_modify_default_config(monkeypatch, tmp_path):
    default_path, user_path = _patch_paths(monkeypatch, tmp_path)
    original_default = default_path.read_text()

    config.update_user_config(("log_level",), "DEBUG")

    assert default_path.read_text() == original_default


def test_parse_config_merges_user_overrides_over_defaults(monkeypatch, tmp_path):
    default_path, user_path = _patch_paths(monkeypatch, tmp_path)

    config.update_user_config(("mail", "imap", "ssl"), False)

    merged = config.parse_config()
    assert merged["mail"]["imap"]["ssl"] is False
    assert merged["mail"]["imap"]["server"] == "imap.example.com"
    assert merged["log_level"] == "INFO"
