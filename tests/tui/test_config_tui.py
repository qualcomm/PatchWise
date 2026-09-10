# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from unittest.mock import patch

from patchwise.utils import config_tui


def _leaf_text(item) -> str:
    return item.show("1")


def test_bool_leaf_tagged_default_and_toggle_persists():
    node = {"ssl": True}
    defaults_root = {"mail": {"imap": {"ssl": True}}}
    key_path = ("mail", "imap", "ssl")

    item = config_tui._build_leaf_item(node, "ssl", key_path, defaults_root, menu=None)

    assert "(default)" in _leaf_text(item)
    assert "ssl = True" in _leaf_text(item)

    with patch.object(config_tui, "update_user_config") as mock_update:
        item.action()

    assert node["ssl"] is False
    mock_update.assert_called_once_with(key_path, False)
    assert "(user)" in _leaf_text(item)


def test_long_string_leaf_label_is_truncated():
    long_message = "PatchWise uses LiteLLM " * 20
    node = {"message": long_message}
    defaults_root = {"api_key_disclaimer": {"message": long_message}}
    key_path = ("api_key_disclaimer", "message")

    item = config_tui._build_leaf_item(
        node, "message", key_path, defaults_root, menu=None
    )

    text = _leaf_text(item)
    assert len(text) <= config_tui.FALLBACK_LABEL_WIDTH + len("1 - ")
    assert text.endswith("…")
    # The untruncated value is still what gets edited/persisted.
    assert node["message"] == long_message


def test_str_leaf_tagged_user_when_overridden():
    node = {"server": "custom.example.com"}
    defaults_root = {"mail": {"imap": {"server": "imap.example.com"}}}
    key_path = ("mail", "imap", "server")

    item = config_tui._build_leaf_item(
        node, "server", key_path, defaults_root, menu=None
    )

    text = _leaf_text(item)
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

    submenu = config_tui.CursesMenu("blocklist")
    config_tui._populate_list_submenu(
        submenu, node, "blocklist", key_path, defaults_root
    )

    # Items: [0] a, [1] b, [2] c, Add new item...
    assert len(submenu.items) == 4

    with patch.object(config_tui, "update_user_config") as mock_update:
        submenu.items[1].action()  # delete "b"

    assert node["blocklist"] == ["a", "c"]
    mock_update.assert_called_once_with(key_path, ["a", "c"])
    assert len(submenu.items) == 3  # re-populated: a, c, Add new item...


def test_list_leaf_add_item_persists_appended_list():
    node = {"blocklist": ["a"]}
    key_path = ("indexing", "blocklist")
    defaults_root = {"indexing": {"blocklist": ["a"]}}

    submenu = config_tui.CursesMenu("blocklist")
    config_tui._populate_list_submenu(
        submenu, node, "blocklist", key_path, defaults_root
    )

    add_item = submenu.items[-1]
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

    assert len(menu.items) == 1
    mail_item = menu.items[0]
    assert isinstance(mail_item, config_tui.SubmenuItem)
    assert mail_item.submenu.title == "mail"


def test_build_menu_creates_list_item_for_list_value():
    tree = {"indexing": {"blocklist": ["a", "b"]}}
    menu = config_tui._build_menu(tree, tree, (), "root", {})

    blocklist_menu = menu.items[0].submenu
    list_item = blocklist_menu.items[0]
    assert isinstance(list_item, config_tui.ConfigSubmenuItem)


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


def test_config_menu_draw_description_shows_current_item_text():
    descriptions = {("k",): "Some helpful explanation."}
    menu = config_tui.ConfigMenu("title", "subtitle", descriptions)

    calls = []

    class FakeScreen:
        def getmaxyx(self):
            return (24, 80)

        def addstr(self, *args, **kwargs):
            calls.append(args)

        def clear(self):
            pass

        def border(self):
            pass

        def refresh(self, *args, **kwargs):
            pass

    menu.screen = FakeScreen()
    item = config_tui.ActionItem("k", lambda: None, menu, ("k",))
    with patch.object(config_tui.CursesMenu, "stdscr", FakeScreen()):
        menu.items.append(item)
        menu.current_option = 0

        menu._draw_description()

    assert any(
        "Some helpful explanation." in arg
        for call in calls
        for arg in call
        if isinstance(arg, str)
    )


def test_config_menu_draw_description_survives_item_mutation():
    """Regression test: _populate_list_submenu's `del submenu.items[:]` triggers a
    synchronous adjust_screen_size() -> draw() while the item list is transiently
    shorter (or empty) than current_option, which must not raise IndexError."""
    node = {"options": ["Yes", "No", "Maybe"]}
    key_path = ("x", "options")
    defaults_root = {"x": {"options": ["Yes", "No", "Maybe"]}}

    class FakeScreen:
        def getmaxyx(self):
            return (24, 80)

        def addstr(self, *args, **kwargs):
            pass

        def clear(self):
            pass

        def border(self):
            pass

        def refresh(self, *args, **kwargs):
            pass

        def resize(self, *args, **kwargs):
            pass

    submenu = config_tui.ConfigMenu("options", "sub", {})
    submenu.screen = FakeScreen()
    with patch.object(config_tui.CursesMenu, "stdscr", FakeScreen()):
        config_tui._populate_list_submenu(
            submenu, node, "options", key_path, defaults_root
        )
        submenu.current_option = submenu.last_item_index  # highlight "Add new item..."

        with patch.object(config_tui, "_prompt_text", return_value="testitem"):
            submenu.items[-1].action()  # add: triggers del + repopulate mid-draw

        assert [i.text for i in submenu.items] == [
            "[0] Yes  (delete)",
            "[1] No  (delete)",
            "[2] Maybe  (delete)",
            "[3] testitem  (delete)",
            "Add new item...",
        ]

        with patch.object(config_tui, "update_user_config"):
            for _ in range(4):
                submenu.items[0].action()  # delete down to empty list

        assert [i.text for i in submenu.items] == ["Add new item..."]


def test_config_menu_draw_clears_pad_before_redraw():
    """Regression test: CursesMenu.draw_item() addstr's onto the pad without erasing
    first, so a shorter redraw after a list add/delete can leave stale characters
    from a previous, longer draw. Plain erase() only marks cells dirty for ncurses'
    line-diffing, which can still skip physical rows once adjust_screen_size()
    resizes the pad and the pad-to-screen mapping shifts; clear() additionally sets
    clearok(TRUE), forcing a full physical redraw. ConfigMenu.draw() must clear
    before redrawing."""
    menu = config_tui.ConfigMenu("title", "subtitle", {})

    calls = []

    class FakeScreen:
        def getmaxyx(self):
            return (24, 80)

        def addstr(self, *args, **kwargs):
            calls.append(("addstr", args))

        def clear(self):
            calls.append(("clear",))

        def border(self):
            calls.append(("border",))

        def refresh(self, *args, **kwargs):
            pass

    menu.screen = FakeScreen()
    menu.stdscr = None
    with patch.object(config_tui.CursesMenu, "stdscr", FakeScreen()):
        menu.draw()

    assert calls[0] == ("clear",)
