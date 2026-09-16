# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Menuconfig-style curses editor for patchwise_config.yaml.

Built on top of ``cursesmenu`` (scrollable bordered menus, submenu navigation, resize
handling) and the stdlib ``curses.textpad.Textbox`` (single-line text editing) rather
than hand-rolled curses plumbing. This module only translates the merged config dict
into a tree of menus/items and persists edits immediately via
``patchwise.utils.config.update_user_config``.
"""

import curses
import curses.ascii
import curses.textpad
import re
import textwrap
from typing import Any, Callable, Dict, List, Optional, Tuple

from cursesmenu import CursesMenu
from cursesmenu.items import SubmenuItem
from cursesmenu.items.menu_item import MenuItem

from patchwise.utils.config import (
    DEFAULT_CONFIG_PATH,
    parse_config,
    read_from_config,
    update_user_config,
)

KeyPath = Tuple[str, ...]

# CursesMenu.draw_item() addstr's a leaf's full label at a fixed column offset with no
# wrapping/truncation of its own (it draws onto a curses.newpad the width of the
# terminal) — a label longer than the available width wraps onto the pad's next
# line(s) and corrupts the rows drawn below it. LABEL_COLUMN/INDEX_PREFIX_MARGIN mirror
# draw_item's own "4, " column offset and "<index> - " prefix so our truncation leaves
# enough room for both.
LABEL_COLUMN = 4
INDEX_PREFIX_MARGIN = 8
FALLBACK_LABEL_WIDTH = 76

# Matches a "key:" or "key: value" line in default_config.yaml, capturing its
# indentation (to track nesting depth) and key name, so leading "# ..." comment
# blocks above it can be collected as that key's description.
_KEY_LINE_RE = re.compile(r"^( *)([A-Za-z0-9_.\-]+):(?:\s+(.*))?$")


def _parse_descriptions(yaml_path) -> Dict[KeyPath, str]:
    """Collect the "# ..." comment block directly above each key in a YAML file,
    keyed by that key's dotted path. Best-effort: a key with no comment above it
    simply has no entry."""
    descriptions: Dict[KeyPath, str] = {}
    stack: List[Tuple[int, str]] = []
    pending: List[str] = []
    with open(yaml_path, "r") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            stripped = line.strip()
            if not stripped:
                pending = []
                continue
            if stripped.startswith("#"):
                pending.append(stripped.lstrip("#").strip())
                continue
            match = _KEY_LINE_RE.match(line)
            if match is None or stripped.startswith("-"):
                pending = []
                continue
            indent = len(match.group(1))
            key = match.group(2)
            while stack and stack[-1][0] >= indent:
                stack.pop()
            key_path = tuple(k for _, k in stack) + (key,)
            stack.append((indent, key))
            if pending:
                descriptions[key_path] = " ".join(pending)
            pending = []
    return descriptions


# Number of pad rows reserved below the item list for the current item's description,
# plus one blank separator row above them.
DESCRIPTION_LINES = 3


class ConfigMenu(CursesMenu):
    """A CursesMenu that erases its pad before every redraw and shows the currently
    highlighted item's description underneath the item list.

    CursesMenu.draw_item() addstr's onto a curses.newpad with no prior erase of that
    row; if a mutation (e.g. adding/deleting a list item, which changes the trailing
    "Return to ... menu" exit-item text length) redraws a shorter string over a
    previously-drawn longer one at the same pad position, the old string's leftover
    characters stay visible. Erasing the whole pad before each draw avoids that,
    regardless of what triggered the redraw.
    """

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        descriptions: Optional[Dict[KeyPath, str]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(title, subtitle, **kwargs)
        self.descriptions: Dict[KeyPath, str] = (
            descriptions if descriptions is not None else {}
        )

    @property
    def menu_height(self) -> int:
        return super().menu_height + 1 + DESCRIPTION_LINES

    def adjust_screen_size(self) -> None:
        # CursesMenu.adjust_screen_size() only resizes the pad when it's shorter
        # than MIN_SIZE + len(all_items), never consulting the menu_height override
        # above — so it undercounts by the 4 rows we reserve for the description,
        # and draw()/_draw_description() below can addstr past the pad's actual
        # row count (raising _curses.error) for several item-count changes before
        # the base check finally catches up and resizes.
        if self.screen:
            max_row, max_cols = self.screen.getmaxyx()
            if max_row < self.menu_height:
                self.screen.resize(self.menu_height, max_cols)
            self.draw()

    def draw(self) -> None:
        assert self.screen is not None
        # clear() (unlike erase()) also sets clearok(TRUE), forcing a full physical
        # terminal redraw on the next refresh instead of ncurses' usual line-diffing.
        # Diffing alone can leave stale bytes on screen once adjust_screen_size()
        # resizes the pad (e.g. after a list add/delete changes the item count) and
        # the pad-to-screen row mapping shifts.
        self.screen.clear()
        self.screen.border()
        self.screen.addstr(2, 2, self.title, curses.A_STANDOUT)
        self.screen.addstr(4, 2, self.subtitle, curses.A_BOLD)
        for index, item in enumerate(self.all_items):
            self.draw_item(index, item)
        self._draw_description()
        self.refresh_screen()

    def _draw_description(self) -> None:
        assert self.screen is not None
        # Don't use self.current_item: ItemGroup mutations (e.g. the
        # `del submenu.items[:]` in _populate_list_submenu) call adjust_screen_size()
        # -> draw() synchronously after every single insert/delete, so current_option
        # can transiently point past the end of (or into an emptied) all_items.
        all_items = self.all_items
        if 0 <= self.current_option < len(all_items):
            key_path = getattr(all_items[self.current_option], "key_path", None)
        else:
            key_path = None
        text = self.descriptions.get(key_path, "") if key_path else ""

        _, max_x = self.screen.getmaxyx()
        width = max(max_x - LABEL_COLUMN - 2, 10)
        lines = textwrap.wrap(text, width)[:DESCRIPTION_LINES] if text else []

        # Item rows end at (parent menu_height - 2); leave the following row blank
        # as a separator, then render up to DESCRIPTION_LINES of wrapped text.
        first_row = super().menu_height
        for offset in range(DESCRIPTION_LINES):
            line = lines[offset] if offset < len(lines) else ""
            self.screen.addstr(first_row + offset, LABEL_COLUMN, line)


class ActionItem(MenuItem):
    """A MenuItem that runs a callback on selection.

    Deliberately does not extend cursesmenu's FunctionItem/ExternalItem: those call
    curses.endwin()/reset_prog_mode() around the callback (meant for shelling out to
    external programs), which would tear down curses state our callbacks rely on to
    draw their own nested windows (e.g. the Textbox editor below).
    """

    def __init__(
        self,
        text: str,
        callback: Callable[[], None],
        menu: Optional[CursesMenu] = None,
        key_path: Optional[KeyPath] = None,
    ) -> None:
        super().__init__(text=text, menu=menu)
        self.callback = callback
        self.key_path = key_path

    def action(self) -> None:
        self.callback()


class ConfigLeafItem(ActionItem):
    """An ActionItem whose displayed text is recomputed on every render."""

    def __init__(
        self,
        label_fn: Callable[[], str],
        callback: Callable[[], None],
        menu: Optional[CursesMenu] = None,
        key_path: Optional[KeyPath] = None,
    ) -> None:
        self._label_fn = label_fn
        super().__init__("", callback, menu, key_path)

    def show(self, index_text: str) -> str:
        self.text = self._label_fn()
        return super().show(index_text)


class ConfigSubmenuItem(SubmenuItem):
    """A SubmenuItem whose displayed text is recomputed on every render."""

    def __init__(
        self,
        label_fn: Callable[[], str],
        submenu: CursesMenu,
        menu: Optional[CursesMenu] = None,
        key_path: Optional[KeyPath] = None,
    ) -> None:
        self._label_fn = label_fn
        self.key_path = key_path
        super().__init__(text="", submenu=submenu, menu=menu)

    def show(self, index_text: str) -> str:
        self.text = self._label_fn()
        return super().show(index_text)


def _format_value(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(str(item) for item in value) + "]"
    return str(value)


def _available_label_width() -> int:
    """Max width for a leaf's rendered label before CursesMenu.draw_item()'s addstr
    wraps it onto (and corrupts) the pad rows below it."""
    stdscr = CursesMenu.stdscr
    if stdscr is None:
        return FALLBACK_LABEL_WIDTH
    _, max_x = stdscr.getmaxyx()
    return max(max_x - LABEL_COLUMN - INDEX_PREFIX_MARGIN, 10)


def _truncate_label(label: str) -> str:
    width = _available_label_width()
    if len(label) <= width:
        return label
    return label[: max(width - 1, 1)] + "…"


def _get_at_path(tree: Dict[str, Any], key_path: KeyPath) -> Tuple[bool, Any]:
    node: Any = tree
    for key in key_path:
        if not isinstance(node, dict) or key not in node:
            return False, None
        node = node[key]
    return True, node


def _is_overridden(
    current_value: Any, key_path: KeyPath, defaults_root: Dict[str, Any]
) -> bool:
    found, default_value = _get_at_path(defaults_root, key_path)
    return (not found) or (current_value != default_value)


def _leaf_label(
    key: str, value: Any, key_path: KeyPath, defaults_root: Dict[str, Any]
) -> str:
    tag = "user" if _is_overridden(value, key_path, defaults_root) else "default"
    return _truncate_label(f"{key} = {_format_value(value)}  ({tag})")


def _leaf_label_fn(
    node: Dict[str, Any],
    key: str,
    key_path: KeyPath,
    defaults_root: Dict[str, Any],
) -> Callable[[], str]:
    def _label() -> str:
        return _leaf_label(key, node[key], key_path, defaults_root)

    return _label


def _prompt_text(prompt: str, initial: str) -> Optional[str]:
    """Show a bordered single-line text editor pre-filled with ``initial``.

    Returns the edited text, or None if the user cancelled with Esc.
    """
    stdscr = CursesMenu.stdscr
    assert stdscr is not None
    max_y, max_x = stdscr.getmaxyx()
    # Size off both the prompt and the initial value — sizing off the prompt alone
    # left long existing values (e.g. api_key_disclaimer.message) truncated in the
    # box before the user ever saw them, so pressing Enter without editing silently
    # persisted a cut-down value.
    width = max(min(max(len(prompt), len(initial)) + 6, max_x - 4), 20)
    height = 5
    start_y = max((max_y - height) // 2, 0)
    start_x = max((max_x - width) // 2, 0)

    win = curses.newwin(height, width, start_y, start_x)
    win.border()
    win.addstr(1, 2, prompt[: width - 4])
    edit_win = win.derwin(1, width - 4, 3, 2)
    edit_win.addstr(0, 0, initial[: width - 5])
    edit_win.move(0, min(len(initial), width - 5))
    win.refresh()
    edit_win.refresh()

    curses.curs_set(1)
    cancelled = False

    def _validate(ch: int) -> int:
        nonlocal cancelled
        if ch == curses.ascii.ESC:
            cancelled = True
            return curses.ascii.BEL
        return ch

    textbox = curses.textpad.Textbox(edit_win, insert_mode=True)
    result = textbox.edit(_validate)
    curses.curs_set(0)

    win.clear()
    win.refresh()

    if cancelled:
        return None
    return result.strip()


def _edit_scalar(node: Dict[str, Any], key: str, key_path: KeyPath) -> None:
    current = node[key]
    new_text = _prompt_text(f"Edit {key}:", str(current))
    if new_text is None:
        return

    new_value: Any
    if isinstance(current, int):
        try:
            new_value = int(new_text)
        except ValueError:
            return
    elif isinstance(current, float):
        try:
            new_value = float(new_text)
        except ValueError:
            return
    else:
        new_value = new_text

    node[key] = new_value
    update_user_config(key_path, new_value)


def _toggle_action_fn(
    node: Dict[str, Any], key: str, key_path: KeyPath
) -> Callable[[], None]:
    def _toggle() -> None:
        new_value = not node[key]
        node[key] = new_value
        update_user_config(key_path, new_value)

    return _toggle


def _scalar_edit_action_fn(
    node: Dict[str, Any], key: str, key_path: KeyPath
) -> Callable[[], None]:
    def _edit() -> None:
        _edit_scalar(node, key, key_path)

    return _edit


def _build_leaf_item(
    node: Dict[str, Any],
    key: str,
    key_path: KeyPath,
    defaults_root: Dict[str, Any],
    menu: CursesMenu,
) -> ConfigLeafItem:
    label_fn = _leaf_label_fn(node, key, key_path, defaults_root)
    value = node[key]
    if isinstance(value, bool):
        action = _toggle_action_fn(node, key, key_path)
    else:
        action = _scalar_edit_action_fn(node, key, key_path)
    return ConfigLeafItem(label_fn, action, menu, key_path)


def _delete_item_action_fn(
    submenu: CursesMenu,
    node: Dict[str, Any],
    key: str,
    key_path: KeyPath,
    defaults_root: Dict[str, Any],
    index: int,
) -> Callable[[], None]:
    def _delete() -> None:
        values = node[key]
        if 0 <= index < len(values):
            del values[index]
            update_user_config(key_path, values)
            _populate_list_submenu(submenu, node, key, key_path, defaults_root)

    return _delete


def _add_item_action_fn(
    submenu: CursesMenu,
    node: Dict[str, Any],
    key: str,
    key_path: KeyPath,
    defaults_root: Dict[str, Any],
) -> Callable[[], None]:
    def _add() -> None:
        new_value = _prompt_text(f"New value for {key}:", "")
        if new_value:
            node[key].append(new_value)
            update_user_config(key_path, node[key])
            _populate_list_submenu(submenu, node, key, key_path, defaults_root)

    return _add


def _populate_list_submenu(
    submenu: CursesMenu,
    node: Dict[str, Any],
    key: str,
    key_path: KeyPath,
    defaults_root: Dict[str, Any],
) -> None:
    del submenu.items[:]
    for index, item_value in enumerate(node[key]):
        delete_action = _delete_item_action_fn(
            submenu, node, key, key_path, defaults_root, index
        )
        submenu.items.append(
            ActionItem(
                _truncate_label(f"[{index}] {item_value}  (delete)"),
                delete_action,
                submenu,
                key_path,
            )
        )
    add_action = _add_item_action_fn(submenu, node, key, key_path, defaults_root)
    submenu.items.append(ActionItem("Add new item...", add_action, submenu, key_path))
    submenu.current_option = min(submenu.current_option, submenu.last_item_index)


def _build_list_item(
    node: Dict[str, Any],
    key: str,
    key_path: KeyPath,
    defaults_root: Dict[str, Any],
    parent_menu: CursesMenu,
    descriptions: Dict[KeyPath, str],
) -> ConfigSubmenuItem:
    label_fn = _leaf_label_fn(node, key, key_path, defaults_root)
    submenu = ConfigMenu(
        key,
        "Select an item to delete, or 'Add new item...' to append.",
        descriptions,
    )
    _populate_list_submenu(submenu, node, key, key_path, defaults_root)
    return ConfigSubmenuItem(label_fn, submenu, parent_menu, key_path)


def _build_menu(
    node: Dict[str, Any],
    defaults_root: Dict[str, Any],
    key_path: KeyPath,
    title: str,
    descriptions: Dict[KeyPath, str],
) -> CursesMenu:
    menu = ConfigMenu(
        title, "Use arrow keys and Enter to browse and edit.", descriptions
    )
    for key, value in node.items():
        child_path = key_path + (key,)
        if isinstance(value, dict):
            submenu = _build_menu(value, defaults_root, child_path, key, descriptions)
            section_item = SubmenuItem(key, submenu, menu)
            section_item.key_path = child_path
            menu.items.append(section_item)
        elif isinstance(value, list):
            menu.items.append(
                _build_list_item(
                    node, key, child_path, defaults_root, menu, descriptions
                )
            )
        else:
            menu.items.append(
                _build_leaf_item(node, key, child_path, defaults_root, menu)
            )
    return menu


def run_config_editor() -> None:
    merged_config = parse_config()
    default_config = read_from_config(DEFAULT_CONFIG_PATH)
    descriptions = _parse_descriptions(DEFAULT_CONFIG_PATH)
    menu = _build_menu(
        merged_config, default_config, (), "PatchWise Configuration", descriptions
    )
    menu.show()
