# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import io
from unittest.mock import patch

import blessed
from blessed.keyboard import Keystroke

from patchwise.utils import config_tui


def _term(force_styling: bool = False) -> "blessed.Terminal":
    return blessed.Terminal(stream=io.StringIO(), force_styling=force_styling)


def test_bool_leaf_tagged_default_and_toggle_persists():
    node = {"ssl": True}
    defaults_root = {"mail": {"imap": {"ssl": True}}}
    key_path = ("mail", "imap", "ssl")

    item = config_tui._build_leaf_item(node, "ssl", key_path, defaults_root)

    assert "(default)" in item.text
    assert "ssl = True" in item.text

    with patch.object(config_tui, "update_user_config") as mock_update:
        item.action()

    assert node["ssl"] is False
    mock_update.assert_called_once_with(key_path, False)
    assert "(user)" in item.text


def test_long_string_leaf_label_is_truncated():
    long_message = "PatchWise uses LiteLLM " * 20
    node = {"message": long_message}
    defaults_root = {"api_key_disclaimer": {"message": long_message}}
    key_path = ("api_key_disclaimer", "message")

    item = config_tui._build_leaf_item(node, "message", key_path, defaults_root)

    text = item.text
    assert len(text) <= config_tui.FALLBACK_LABEL_WIDTH
    assert text.endswith("…")
    # The untruncated value is still what gets edited/persisted.
    assert node["message"] == long_message


def test_str_leaf_tagged_user_when_overridden():
    node = {"server": "custom.example.com"}
    defaults_root = {"mail": {"imap": {"server": "imap.example.com"}}}
    key_path = ("mail", "imap", "server")

    item = config_tui._build_leaf_item(node, "server", key_path, defaults_root)

    text = item.text
    assert "(user)" in text
    assert "custom.example.com" in text


def test_scalar_edit_persists_new_string_value():
    node = {"server": "imap.example.com"}
    key_path = ("mail", "imap", "server")

    with (
        patch.object(config_tui, "_prompt_text", return_value="new.example.com"),
        patch.object(config_tui, "update_user_config") as mock_update,
    ):
        config_tui._edit_scalar(node, "server", key_path)

    assert node["server"] == "new.example.com"
    mock_update.assert_called_once_with(key_path, "new.example.com")


def test_scalar_edit_casts_back_to_int():
    node = {"port": 993}
    key_path = ("mail", "imap", "port")

    with (
        patch.object(config_tui, "_prompt_text", return_value="995"),
        patch.object(config_tui, "update_user_config") as mock_update,
    ):
        config_tui._edit_scalar(node, "port", key_path)

    assert node["port"] == 995
    mock_update.assert_called_once_with(key_path, 995)


def test_scalar_edit_cancelled_leaves_value_untouched():
    node = {"server": "imap.example.com"}
    key_path = ("mail", "imap", "server")

    with (
        patch.object(config_tui, "_prompt_text", return_value=None),
        patch.object(config_tui, "update_user_config") as mock_update,
    ):
        config_tui._edit_scalar(node, "server", key_path)

    assert node["server"] == "imap.example.com"
    mock_update.assert_not_called()


def test_scalar_edit_invalid_int_leaves_value_untouched():
    node = {"port": 993}
    key_path = ("mail", "imap", "port")

    with (
        patch.object(config_tui, "_prompt_text", return_value="not-a-number"),
        patch.object(config_tui, "update_user_config") as mock_update,
    ):
        config_tui._edit_scalar(node, "port", key_path)

    assert node["port"] == 993
    mock_update.assert_not_called()


def test_list_leaf_delete_item_persists_shortened_list():
    node = {"blocklist": ["a", "b", "c"]}
    key_path = ("indexing", "blocklist")
    defaults_root = {"indexing": {"blocklist": ["a", "b", "c"]}}

    submenu = config_tui.Menu("blocklist")
    config_tui._populate_list_submenu(
        submenu, node, "blocklist", key_path, defaults_root
    )

    # Items: [0] a, [1] b, [2] c, Add new item..., Restore Defaults
    assert len(submenu.items) == 5

    with patch.object(config_tui, "update_user_config") as mock_update:
        submenu.items[1].action()  # delete "b"

    assert node["blocklist"] == ["a", "c"]
    mock_update.assert_called_once_with(key_path, ["a", "c"])
    assert (
        len(submenu.items) == 4
    )  # re-populated: a, c, Add new item..., Restore Defaults


def test_list_leaf_add_item_persists_appended_list():
    node = {"blocklist": ["a"]}
    key_path = ("indexing", "blocklist")
    defaults_root = {"indexing": {"blocklist": ["a"]}}

    submenu = config_tui.Menu("blocklist")
    config_tui._populate_list_submenu(
        submenu, node, "blocklist", key_path, defaults_root
    )

    add_item = submenu.items[-2]
    assert "Add new item" in add_item.text

    with (
        patch.object(config_tui, "_prompt_text", return_value="new-item"),
        patch.object(config_tui, "update_user_config") as mock_update,
    ):
        add_item.action()

    assert node["blocklist"] == ["a", "new-item"]
    mock_update.assert_called_once_with(key_path, ["a", "new-item"])


def test_build_menu_creates_submenu_for_nested_dict():
    tree = {"mail": {"imap": {"ssl": True}}}
    menu = config_tui._build_menu(tree, tree, (), "root", {})

    assert len(menu.items) == 2  # mail section + Restore Defaults
    mail_item = menu.items[0]
    assert mail_item.submenu is not None
    assert mail_item.submenu.title == "mail"


def test_build_menu_creates_list_item_for_list_value():
    tree = {"indexing": {"blocklist": ["a", "b"]}}
    menu = config_tui._build_menu(tree, tree, (), "root", {})

    blocklist_menu = menu.items[0].submenu
    list_item = blocklist_menu.items[0]
    assert list_item.submenu is not None


def test_build_menu_wires_key_path_and_description_into_leaf():
    tree = {"mail": {"imap": {"ssl": True}}}
    descriptions = {("mail", "imap", "ssl"): "Whether to connect over SSL."}
    menu = config_tui._build_menu(tree, tree, (), "root", descriptions)

    ssl_item = menu.items[0].submenu.items[0].submenu.items[0]
    assert ssl_item.key_path == ("mail", "imap", "ssl")


def test_parse_descriptions_collects_comment_above_key(tmp_path):
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "top:\n"
        "    # First line.\n"
        "    # Second line.\n"
        "    nested: 1\n"
        "    no_comment: 2\n"
    )

    descriptions = config_tui._parse_descriptions(yaml_path)

    assert descriptions[("top", "nested")] == "First line. Second line."
    assert ("top", "no_comment") not in descriptions


def test_render_frame_shows_current_item_description():
    descriptions = {("k",): "Some helpful explanation."}
    menu = config_tui.Menu("title", "subtitle", descriptions)
    menu.items.append(config_tui.Item("k", action=lambda: None, key_path=("k",)))
    menu.current_option = 0

    frame = config_tui._render_frame(_term(), menu)

    assert "Some helpful explanation." in frame


def test_render_frame_clears_screen_before_content():
    """Every frame is a full, stateless redraw (home+clear, then content) — there
    is no persistent pad/state a mutation could leave stale content in, unlike the
    old cursesmenu-based draw() which had to erase its pad explicitly to avoid
    leftover characters from a previous, longer draw."""
    menu = config_tui.Menu("title", "subtitle", {})

    frame = config_tui._render_frame(_term(force_styling=True), menu)

    term = _term(force_styling=True)
    assert frame.startswith(term.home + term.clear)


def test_list_submenu_add_then_delete_rebuilds_items_correctly():
    node = {"options": ["Yes", "No", "Maybe"]}
    key_path = ("x", "options")
    defaults_root = {"x": {"options": ["Yes", "No", "Maybe"]}}

    submenu = config_tui.Menu("options", "sub", {})
    config_tui._populate_list_submenu(submenu, node, "options", key_path, defaults_root)
    submenu.current_option = len(submenu.items) - 2  # "Add new item..."

    with patch.object(config_tui, "_prompt_text", return_value="testitem"):
        submenu.items[-2].action()  # add

    assert [i.text for i in submenu.items] == [
        "[0] Yes  (delete)",
        "[1] No  (delete)",
        "[2] Maybe  (delete)",
        "[3] testitem  (delete)",
        "Add new item...",
        "Restore Defaults",
    ]

    with patch.object(config_tui, "update_user_config"):
        for _ in range(4):
            submenu.items[0].action()  # delete down to empty list

    assert [i.text for i in submenu.items] == [
        "Add new item...",
        "Restore Defaults",
    ]


def test_populate_map_submenu_lists_entries_and_add_control():
    node = {"models": {"openai/Pro": "GPT-5"}}
    key_path = ("ai", "models")
    defaults_root = {"ai": {"models": {}}}

    submenu = config_tui.Menu("models")
    config_tui._populate_map_submenu(
        submenu, node, "models", key_path, defaults_root, {}
    )

    assert [i.text for i in submenu.items] == [
        "openai/Pro = GPT-5  (user)",
        "Add new item...",
        "Restore Defaults",
    ]


def test_map_add_item_persists_new_key_value():
    node = {"models": {}}
    key_path = ("ai", "models")
    defaults_root = {"ai": {"models": {}}}

    submenu = config_tui.Menu("models")
    config_tui._populate_map_submenu(
        submenu, node, "models", key_path, defaults_root, {}
    )
    add_item = submenu.items[-2]
    assert "Add new item" in add_item.text

    with (
        patch.object(
            config_tui,
            "_prompt_text",
            side_effect=["claude-opus-4-6", "Claude Opus 4.6"],
        ),
        patch.object(config_tui, "update_user_config") as mock_update,
    ):
        add_item.action()

    assert node["models"] == {"claude-opus-4-6": "Claude Opus 4.6"}
    mock_update.assert_called_once_with(
        ("ai", "models", "claude-opus-4-6"), "Claude Opus 4.6"
    )
    assert [i.text for i in submenu.items] == [
        "claude-opus-4-6 = Claude Opus 4.6  (user)",
        "Add new item...",
        "Restore Defaults",
    ]


def test_build_menu_builds_map_item_for_flat_string_map_path():
    tree = {"ai": {"models": {"openai/Pro": "GPT-5"}}}
    menu = config_tui._build_menu(tree, tree, (), "root", {})

    ai_menu = menu.items[0].submenu
    models_item = ai_menu.items[0]
    assert models_item.submenu is not None
    assert models_item.submenu.items[0].text == "openai/Pro = GPT-5  (default)"


def test_restore_defaults_confirmed_resets_list_and_persists():
    node = {"blocklist": ["a", "user-added"]}
    key_path = ("indexing", "blocklist")
    defaults_root = {"indexing": {"blocklist": ["a"]}}

    submenu = config_tui.Menu("blocklist")
    config_tui._populate_list_submenu(
        submenu, node, "blocklist", key_path, defaults_root
    )
    restore_item = submenu.items[-1]
    assert restore_item.text == "Restore Defaults"

    with (
        patch.object(config_tui, "_prompt_text", return_value="yes"),
        patch.object(config_tui, "reset_user_config") as mock_reset,
    ):
        restore_item.action()

    mock_reset.assert_called_once_with(key_path)
    assert node["blocklist"] == ["a"]
    assert [i.text for i in submenu.items] == [
        "[0] a  (delete)",
        "Add new item...",
        "Restore Defaults",
    ]


def test_restore_defaults_not_confirmed_leaves_list_untouched():
    node = {"blocklist": ["a", "user-added"]}
    key_path = ("indexing", "blocklist")
    defaults_root = {"indexing": {"blocklist": ["a"]}}

    submenu = config_tui.Menu("blocklist")
    config_tui._populate_list_submenu(
        submenu, node, "blocklist", key_path, defaults_root
    )
    restore_item = submenu.items[-1]

    with (
        patch.object(config_tui, "_prompt_text", return_value="no"),
        patch.object(config_tui, "reset_user_config") as mock_reset,
    ):
        restore_item.action()

    mock_reset.assert_not_called()
    assert node["blocklist"] == ["a", "user-added"]


def test_restore_defaults_on_map_resets_entries_and_persists():
    node = {"models": {"openai/Pro": "GPT-5", "claude": "Opus"}}
    key_path = ("ai", "models")
    defaults_root = {"ai": {"models": {}}}

    submenu = config_tui.Menu("models")
    config_tui._populate_map_submenu(
        submenu, node, "models", key_path, defaults_root, {}
    )
    restore_item = submenu.items[-1]

    with (
        patch.object(config_tui, "_prompt_text", return_value="yes"),
        patch.object(config_tui, "reset_user_config") as mock_reset,
    ):
        restore_item.action()

    mock_reset.assert_called_once_with(key_path)
    assert node["models"] == {}
    assert [i.text for i in submenu.items] == ["Add new item...", "Restore Defaults"]


def test_restore_defaults_on_section_rebuilds_nested_items():
    tree = {"mail": {"imap": {"ssl": False, "server": "custom.example.com"}}}
    defaults_root = {"mail": {"imap": {"ssl": True, "server": "imap.example.com"}}}
    menu = config_tui._build_menu(tree, defaults_root, (), "root", {})
    mail_menu = menu.items[0].submenu
    imap_menu = mail_menu.items[0].submenu
    restore_item = imap_menu.items[-1]
    assert restore_item.text == "Restore Defaults"

    with (
        patch.object(config_tui, "_prompt_text", return_value="yes"),
        patch.object(config_tui, "reset_user_config") as mock_reset,
    ):
        restore_item.action()

    mock_reset.assert_called_once_with(("mail", "imap"))
    assert tree["mail"]["imap"] == {"ssl": True, "server": "imap.example.com"}
    labels = [i.text for i in imap_menu.items]
    assert "ssl = True  (default)" in labels
    assert "server = imap.example.com  (default)" in labels


def test_restore_defaults_on_root_wipes_whole_config():
    tree = {"log_level": "DEBUG", "mail": {"imap": {"ssl": False}}}
    defaults_root = {"log_level": "INFO", "mail": {"imap": {"ssl": True}}}
    menu = config_tui._build_menu(tree, defaults_root, (), "root", {})
    restore_item = menu.items[-1]

    with (
        patch.object(config_tui, "_prompt_text", return_value="yes"),
        patch.object(config_tui, "reset_user_config") as mock_reset,
    ):
        restore_item.action()

    mock_reset.assert_called_once_with(())
    assert tree == {"log_level": "INFO", "mail": {"imap": {"ssl": True}}}


def test_restore_action_does_not_alias_defaults_root():
    """A restore must deep-copy the default subtree — aliasing defaults_root's own
    nested dict/list would let a later edit on the restored node mutate
    defaults_root itself, corrupting unrelated (default) tags elsewhere."""
    tree = {"indexing": {"blocklist": ["a", "extra"]}}
    defaults_root = {"indexing": {"blocklist": ["a"]}}
    menu = config_tui._build_menu(tree, defaults_root, (), "root", {})
    blocklist_menu = menu.items[0].submenu.items[0].submenu
    restore_item = blocklist_menu.items[-1]

    with (
        patch.object(config_tui, "_prompt_text", return_value="yes"),
        patch.object(config_tui, "reset_user_config"),
    ):
        restore_item.action()

    tree["indexing"]["blocklist"].append("mutated-after-restore")

    assert defaults_root["indexing"]["blocklist"] == ["a"]


def test_run_menu_left_arrow_at_root_is_noop_not_quit():
    """Left/Escape at the root menu must not pop the last menu off the
    navigation stack — that would empty the stack and end the loop, silently
    exiting the whole editor instead of just staying on the home screen."""
    menu = config_tui.Menu("root")
    menu.items.append(config_tui.Item("leaf", action=lambda: None))
    term = _term()

    keys = iter(
        [
            Keystroke("", code=term.KEY_LEFT, name="KEY_LEFT"),
            Keystroke("", code=term.KEY_ESCAPE, name="KEY_ESCAPE"),
            Keystroke("q"),
        ]
    )

    with patch.object(term, "inkey", side_effect=lambda timeout=None: next(keys)):
        config_tui._run_menu(term, menu)  # returns instead of hanging/erroring


def test_run_menu_left_arrow_backs_out_of_submenu_without_quitting():
    submenu = config_tui.Menu("child")
    submenu.items.append(config_tui.Item("leaf", action=lambda: None))
    root = config_tui.Menu("root")
    root.items.append(config_tui.Item("child", submenu=submenu))
    term = _term()

    keys = iter(
        [
            Keystroke("", code=term.KEY_RIGHT, name="KEY_RIGHT"),  # enter submenu
            Keystroke("", code=term.KEY_LEFT, name="KEY_LEFT"),  # back to root
            Keystroke("", code=term.KEY_LEFT, name="KEY_LEFT"),  # no-op at root
            Keystroke("q"),
        ]
    )

    with patch.object(term, "inkey", side_effect=lambda timeout=None: next(keys)):
        config_tui._run_menu(term, root)
