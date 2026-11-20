# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Menuconfig-style editor for patchwise_config.yaml, built on ``blessed``.

``blessed`` re-measures the terminal (``term.height``/``term.width``) straight from
the tty on every access rather than caching pad/window geometry, so a plain
full-redraw-every-frame loop is resize-safe by construction: there is no persistent
geometry that a burst of resize events can desync (unlike a curses pad, whose
cached row/col bookkeping can go out of bounds mid-resize and raise ``curses.error``
on an unguarded background thread). This mirrors the terminal-control approach
``patchwise/ui/screen.py`` already uses for the live review dashboard.

This module only translates the merged config dict into a tree of ``Menu``/``Item``
objects and persists edits immediately via
``patchwise.utils.config.update_user_config``.
"""

import copy
import re
import textwrap
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple, Union

import blessed

from patchwise.utils.config import (
    DEFAULT_CONFIG_PATH,
    parse_config,
    read_from_config,
    reset_user_config,
    update_user_config,
)

KeyPath = Tuple[str, ...]

# Config dicts that default to {} and hold plain scalar values, so an
# "Add new item..." control can safely prompt for a single key + value string.
# Not a general rule for every empty-default dict: mail.deprecated_lists also
# defaults to {} but its entries are nested DeprecatedList objects
# (mail_handler/config.py), which a single-string prompt would corrupt.
FLAT_STRING_MAP_PATHS: FrozenSet[KeyPath] = frozenset({("ai", "models")})

# A label longer than the terminal width would wrap onto the next terminal row and
# shift every row drawn below it, since a frame is plain lines with no per-row
# clipping. LABEL_COLUMN mirrors the couple of columns of margin the description
# text below the item list is also given.
LABEL_COLUMN = 2
FALLBACK_LABEL_WIDTH = 76

# Rows reserved below the item list: one blank separator, then up to this many
# wrapped lines of the current item's description.
DESCRIPTION_LINES = 3

# Matches a "key:" or "key: value" line in default_config.yaml, capturing its
# indentation (to track nesting depth) and key name, so leading "# ..." comment
# blocks above it can be collected as that key's description.
_KEY_LINE_RE = re.compile(r"^( *)([A-Za-z0-9_.\-]+):(?:\s+(.*))?$")

# The Terminal currently driving the editor, if any. Used only to size labels to
# the live terminal width; falls back to FALLBACK_LABEL_WIDTH outside of a running
# editor (e.g. in tests, which build Item/Menu objects directly).
_ACTIVE_TERM: Optional["blessed.Terminal"] = None


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


class Item:
    """One selectable row in a Menu.

    ``label_fn`` may be a plain string or a zero-arg callable recomputed on every
    render (so a leaf's "(user)"/"(default)" tag stays live after an edit).
    Exactly one of ``submenu``/``action`` is normally set: Enter pushes ``submenu``
    if present, otherwise calls ``action``.
    """

    def __init__(
        self,
        label_fn: Union[str, Callable[[], str]],
        action: Optional[Callable[[], None]] = None,
        submenu: Optional["Menu"] = None,
        key_path: Optional[KeyPath] = None,
    ) -> None:
        self.label_fn = label_fn
        self.action = action
        self.submenu = submenu
        self.key_path = key_path

    @property
    def text(self) -> str:
        return self.label_fn() if callable(self.label_fn) else self.label_fn


class Menu:
    """A titled, scrollable list of Items."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        descriptions: Optional[Dict[KeyPath, str]] = None,
    ) -> None:
        self.title = title
        self.subtitle = subtitle
        self.descriptions: Dict[KeyPath, str] = (
            descriptions if descriptions is not None else {}
        )
        self.items: List[Item] = []
        self.current_option = 0

    def clamp_selection(self) -> None:
        if not self.items:
            self.current_option = 0
        else:
            self.current_option = max(0, min(self.current_option, len(self.items) - 1))


def _format_value(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(str(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {v}" for k, v in value.items()) + "}"
    return str(value)


def _available_label_width() -> int:
    if _ACTIVE_TERM is None or not _ACTIVE_TERM.width:
        return FALLBACK_LABEL_WIDTH
    return max(_ACTIVE_TERM.width - LABEL_COLUMN - 2, 10)


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


def _render_frame(term: "blessed.Terminal", menu: Menu) -> str:
    """Build one full-screen frame for ``menu`` as a plain string, sized off the
    terminal's *current* height/width. Called fresh on every loop iteration, so a
    mid-resize frame simply picks up the new dimensions next time — there is no
    cached geometry to go stale."""
    width = term.width or (FALLBACK_LABEL_WIDTH + LABEL_COLUMN + 2)
    height = term.height or 24

    lines: List[str] = [term.reverse(menu.title), term.bold(menu.subtitle), ""]
    header_rows = len(lines)
    footer_rows = 1
    reserved_below_items = 1 + DESCRIPTION_LINES + footer_rows
    available = max(height - header_rows - reserved_below_items, 1)

    top = 0
    if menu.items:
        if menu.current_option >= top + available:
            top = menu.current_option - available + 1
        top = max(0, min(top, max(0, len(menu.items) - available)))
    visible = menu.items[top : top + available]

    for offset, item in enumerate(visible):
        index = top + offset
        label = _truncate_label(item.text)
        lines.append(term.reverse(label) if index == menu.current_option else label)
    while len(lines) < header_rows + available:
        lines.append("")

    lines.append("")
    key_path = menu.items[menu.current_option].key_path if menu.items else None
    description = menu.descriptions.get(key_path, "") if key_path else ""
    desc_lines = (
        textwrap.wrap(description, max(width - LABEL_COLUMN, 10))[:DESCRIPTION_LINES]
        if description
        else []
    )
    for i in range(DESCRIPTION_LINES):
        lines.append(desc_lines[i] if i < len(desc_lines) else "")

    lines.append("↑/↓ Move  Enter Select  Esc/← Back  q Quit")

    return term.home + term.clear + "\r\n".join(lines)


def _draw(term: "blessed.Terminal", menu: Menu) -> None:
    term.stream.write(_render_frame(term, menu))
    term.stream.flush()


def _prompt_text(prompt: str, initial: str) -> Optional[str]:
    """Show a single-line text prompt pre-filled with ``initial``.

    Returns the edited text, or None if the user cancelled with Esc.
    """
    term = _ACTIVE_TERM
    assert term is not None
    buf = list(initial)
    cancelled = False
    while True:
        frame = term.home + term.clear
        frame += term.bold(prompt) + "\r\n\r\n"
        frame += "".join(buf)
        term.stream.write(frame)
        term.stream.flush()

        key = term.inkey()
        if key.code == term.KEY_ESCAPE:
            cancelled = True
            break
        if key.code == term.KEY_ENTER or key in ("\n", "\r"):
            break
        if key.code in (term.KEY_BACKSPACE, term.KEY_DELETE) or key in (
            "\x7f",
            "\x08",
        ):
            if buf:
                buf.pop()
            continue
        if key and not key.is_sequence:
            buf.append(str(key))

    if cancelled:
        return None
    return "".join(buf).strip()


def _confirm_restore(label: str) -> bool:
    """Ask the user to type "yes" before restoring defaults for ``label``.

    Reuses the text-entry prompt rather than adding a separate yes/no widget:
    this is a destructive action (it discards user overrides), so it shouldn't be
    a single accidental keypress away.
    """
    answer = _prompt_text(f"Type 'yes' to restore defaults for '{label}':", "")
    return (answer or "").strip().lower() == "yes"


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
) -> Item:
    label_fn = _leaf_label_fn(node, key, key_path, defaults_root)
    value = node[key]
    if isinstance(value, bool):
        action = _toggle_action_fn(node, key, key_path)
    else:
        action = _scalar_edit_action_fn(node, key, key_path)
    return Item(label_fn, action=action, key_path=key_path)


def _delete_item_action_fn(
    submenu: Menu,
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
    submenu: Menu,
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


def _restore_list_action_fn(
    submenu: Menu,
    node: Dict[str, Any],
    key: str,
    key_path: KeyPath,
    defaults_root: Dict[str, Any],
) -> Callable[[], None]:
    def _restore() -> None:
        if not _confirm_restore(key):
            return
        reset_user_config(key_path)
        found, default_value = _get_at_path(defaults_root, key_path)
        node[key] = copy.deepcopy(default_value) if found else []
        _populate_list_submenu(submenu, node, key, key_path, defaults_root)

    return _restore


def _populate_list_submenu(
    submenu: Menu,
    node: Dict[str, Any],
    key: str,
    key_path: KeyPath,
    defaults_root: Dict[str, Any],
) -> None:
    submenu.items = []
    for index, item_value in enumerate(node[key]):
        delete_action = _delete_item_action_fn(
            submenu, node, key, key_path, defaults_root, index
        )
        label = _truncate_label(f"[{index}] {item_value}  (delete)")
        submenu.items.append(Item(label, action=delete_action, key_path=key_path))
    add_action = _add_item_action_fn(submenu, node, key, key_path, defaults_root)
    submenu.items.append(Item("Add new item...", action=add_action, key_path=key_path))
    restore_action = _restore_list_action_fn(
        submenu, node, key, key_path, defaults_root
    )
    submenu.items.append(
        Item("Restore Defaults", action=restore_action, key_path=key_path)
    )
    submenu.clamp_selection()


def _build_list_item(
    node: Dict[str, Any],
    key: str,
    key_path: KeyPath,
    defaults_root: Dict[str, Any],
    descriptions: Dict[KeyPath, str],
) -> Item:
    label_fn = _leaf_label_fn(node, key, key_path, defaults_root)
    submenu = Menu(
        key,
        "Select an item to delete, or 'Add new item...' to append.",
        descriptions,
    )
    _populate_list_submenu(submenu, node, key, key_path, defaults_root)
    return Item(label_fn, submenu=submenu, key_path=key_path)


def _add_map_item_action_fn(
    submenu: Menu,
    node: Dict[str, Any],
    key: str,
    key_path: KeyPath,
    defaults_root: Dict[str, Any],
    descriptions: Dict[KeyPath, str],
) -> Callable[[], None]:
    def _add() -> None:
        new_key = _prompt_text(f"New key for {key}:", "")
        if not new_key:
            return
        new_value = _prompt_text(f"Value for {new_key}:", "")
        if new_value is None:
            return
        node[key][new_key] = new_value
        update_user_config(key_path + (new_key,), new_value)
        _populate_map_submenu(submenu, node, key, key_path, defaults_root, descriptions)

    return _add


def _restore_map_action_fn(
    submenu: Menu,
    node: Dict[str, Any],
    key: str,
    key_path: KeyPath,
    defaults_root: Dict[str, Any],
    descriptions: Dict[KeyPath, str],
) -> Callable[[], None]:
    def _restore() -> None:
        if not _confirm_restore(key):
            return
        reset_user_config(key_path)
        found, default_value = _get_at_path(defaults_root, key_path)
        node[key] = copy.deepcopy(default_value) if found else {}
        _populate_map_submenu(submenu, node, key, key_path, defaults_root, descriptions)

    return _restore


def _populate_map_submenu(
    submenu: Menu,
    node: Dict[str, Any],
    key: str,
    key_path: KeyPath,
    defaults_root: Dict[str, Any],
    descriptions: Dict[KeyPath, str],
) -> None:
    submenu.items = []
    for child_key in node[key]:
        child_path = key_path + (child_key,)
        submenu.items.append(
            _build_leaf_item(node[key], child_key, child_path, defaults_root)
        )
    add_action = _add_map_item_action_fn(
        submenu, node, key, key_path, defaults_root, descriptions
    )
    submenu.items.append(Item("Add new item...", action=add_action, key_path=key_path))
    restore_action = _restore_map_action_fn(
        submenu, node, key, key_path, defaults_root, descriptions
    )
    submenu.items.append(
        Item("Restore Defaults", action=restore_action, key_path=key_path)
    )
    submenu.clamp_selection()


def _build_map_item(
    node: Dict[str, Any],
    key: str,
    key_path: KeyPath,
    defaults_root: Dict[str, Any],
    descriptions: Dict[KeyPath, str],
) -> Item:
    label_fn = _leaf_label_fn(node, key, key_path, defaults_root)
    submenu = Menu(
        key,
        "Select an item to edit, or 'Add new item...' to append.",
        descriptions,
    )
    _populate_map_submenu(submenu, node, key, key_path, defaults_root, descriptions)
    return Item(label_fn, submenu=submenu, key_path=key_path)


def _restore_section_action_fn(
    menu: Menu,
    node: Dict[str, Any],
    key_path: KeyPath,
    defaults_root: Dict[str, Any],
    descriptions: Dict[KeyPath, str],
) -> Callable[[], None]:
    def _restore() -> None:
        if not _confirm_restore(menu.title):
            return
        reset_user_config(key_path)
        found, default_value = _get_at_path(defaults_root, key_path)
        node.clear()
        node.update(copy.deepcopy(default_value) if found else {})
        _populate_section_menu(menu, node, key_path, defaults_root, descriptions)

    return _restore


def _populate_section_menu(
    menu: Menu,
    node: Dict[str, Any],
    key_path: KeyPath,
    defaults_root: Dict[str, Any],
    descriptions: Dict[KeyPath, str],
) -> None:
    menu.items = []
    for key, value in node.items():
        child_path = key_path + (key,)
        if isinstance(value, dict) and child_path in FLAT_STRING_MAP_PATHS:
            menu.items.append(
                _build_map_item(node, key, child_path, defaults_root, descriptions)
            )
        elif isinstance(value, dict):
            submenu = _build_menu(value, defaults_root, child_path, key, descriptions)
            menu.items.append(Item(key, submenu=submenu, key_path=child_path))
        elif isinstance(value, list):
            menu.items.append(
                _build_list_item(node, key, child_path, defaults_root, descriptions)
            )
        else:
            menu.items.append(_build_leaf_item(node, key, child_path, defaults_root))
    restore_action = _restore_section_action_fn(
        menu, node, key_path, defaults_root, descriptions
    )
    menu.items.append(
        Item("Restore Defaults", action=restore_action, key_path=key_path)
    )
    menu.clamp_selection()


def _build_menu(
    node: Dict[str, Any],
    defaults_root: Dict[str, Any],
    key_path: KeyPath,
    title: str,
    descriptions: Dict[KeyPath, str],
) -> Menu:
    menu = Menu(title, "Use arrow keys and Enter to browse and edit.", descriptions)
    _populate_section_menu(menu, node, key_path, defaults_root, descriptions)
    return menu


def _run_menu(term: "blessed.Terminal", root_menu: Menu) -> None:
    stack: List[Menu] = [root_menu]
    while stack:
        menu = stack[-1]
        menu.clamp_selection()
        _draw(term, menu)

        # A timeout means "nothing happened in the last 0.3s" (no keypress) — the
        # loop simply comes back around and redraws off the terminal's current
        # height/width, so a resize is picked up on the very next frame with no
        # separate resize handling needed.
        key = term.inkey(timeout=0.3)
        if not key:
            continue

        if key.code == term.KEY_UP:
            if menu.items:
                menu.current_option = (menu.current_option - 1) % len(menu.items)
        elif key.code == term.KEY_DOWN:
            if menu.items:
                menu.current_option = (menu.current_option + 1) % len(menu.items)
        elif key.code in (term.KEY_ENTER, term.KEY_RIGHT) or key in ("\n", "\r"):
            if menu.items:
                item = menu.items[menu.current_option]
                if item.submenu is not None:
                    stack.append(item.submenu)
                elif item.action is not None:
                    item.action()
        elif key.code in (term.KEY_LEFT, term.KEY_ESCAPE):
            # Left/Escape go back a level; at the root there's no level to go
            # back to, so treat it as a no-op rather than popping the last
            # menu off the stack (which would end the loop and silently quit).
            if len(stack) > 1:
                stack.pop()
        elif key.lower() == "q":
            stack.clear()


def run_config_editor() -> None:
    global _ACTIVE_TERM

    merged_config = parse_config()
    default_config = read_from_config(DEFAULT_CONFIG_PATH)
    descriptions = _parse_descriptions(DEFAULT_CONFIG_PATH)
    menu = _build_menu(
        merged_config, default_config, (), "PatchWise Configuration", descriptions
    )

    term = blessed.Terminal()
    _ACTIVE_TERM = term
    try:
        with term.fullscreen(), term.cbreak(), term.hidden_cursor():
            _run_menu(term, menu)
    finally:
        _ACTIVE_TERM = None
