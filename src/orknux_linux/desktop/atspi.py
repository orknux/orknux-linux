"""What is inside a window, through AT-SPI2: the accessibility tree GTK, Qt, Firefox and LibreOffice publish.

A window found by X11 is matched to its AT-SPI frame by the process that owns
it and its title; the frame's tree becomes the snapshot, and a ref in it is
an accessible object the runner can focus, measure and act on.
"""

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402

from ..core.snapshot import CONTROLS, RefTable, SnapNode  # noqa: E402

MOST_NODES = 2000
DEEPEST = 40

# AT-SPI's role names, in the vocabulary the Windows client's snapshot speaks, so a model reads one language.
ROLES = {
    "push button": "button", "toggle button": "button", "button": "button",
    "entry": "edit", "password text": "edit", "text": "edit", "editbar": "edit",
    "combo box": "combobox", "check box": "checkbox", "check menu item": "menuitem",
    "radio button": "radiobutton", "radio menu item": "menuitem", "link": "hyperlink",
    "list item": "listitem", "menu item": "menuitem", "menu": "menuitem", "page tab": "tabitem",
    "tree item": "treeitem", "table cell": "dataitem", "slider": "slider", "spin button": "spinner",
    "menu bar": "menubar", "scroll bar": "scrollbar", "document frame": "document", "document web": "document",
    "document text": "document", "column header": "headeritem", "table column header": "headeritem",
    "label": "text", "static": "text", "paragraph": "text", "caption": "text",
    "image": "image", "icon": "image", "heading": "header",
}

FRAMES = {"frame", "window", "dialog", "alert", "file chooser"}


def init():
    Atspi.init()


def role_of(element) -> str:
    try:
        name = element.get_role_name() or ""
    except Exception:
        return "custom"
    mapped = ROLES.get(name, name.replace(" ", ""))
    # A text role that cannot be edited is text to read, not a box to type into.
    if mapped == "edit" and name == "text" and not _has(element, Atspi.StateType.EDITABLE):
        return "text"
    return mapped


def _has(element, state) -> bool:
    try:
        return element.get_state_set().contains(state)
    except Exception:
        return False


def states_of(element) -> list[str]:
    said = []
    for state, word in ((Atspi.StateType.FOCUSED, "focused"), (Atspi.StateType.CHECKED, "checked"),
                        (Atspi.StateType.SELECTED, "selected"), (Atspi.StateType.EXPANDED, "expanded")):
        if _has(element, state):
            said.append(word)
    if _has(element, Atspi.StateType.EXPANDABLE) and not _has(element, Atspi.StateType.EXPANDED):
        said.append("collapsed")
    if not _has(element, Atspi.StateType.SENSITIVE) and not _has(element, Atspi.StateType.ENABLED):
        said.append("disabled")
    return said


def text_of(element) -> str | None:
    try:
        text = element.get_text_iface()
        if text is None:
            return None
        return text.get_text(0, text.get_character_count())
    except Exception:
        return None


def name_of(element) -> str:
    try:
        return element.get_name() or ""
    except Exception:
        return ""


def children(element):
    try:
        count = element.get_child_count()
    except Exception:
        return
    for index in range(count):
        try:
            child = element.get_child_at_index(index)
        except Exception:
            child = None
        if child is not None:
            yield child


def frames():
    """Every top-level frame of every application on the accessibility bus, with its process."""
    desktop = Atspi.get_desktop(0)
    for app in children(desktop):
        try:
            pid = app.get_process_id()
        except Exception:
            pid = None
        for frame in children(app):
            try:
                role = frame.get_role_name()
            except Exception:
                continue
            if role in FRAMES:
                yield pid, frame


def frame_for(pid: int | None, title: str):
    """The AT-SPI frame of a window: its process and title both, else either."""
    candidates = list(frames())
    same_pid = [frame for frame_pid, frame in candidates if pid is not None and frame_pid == pid]
    for frame in same_pid:
        if name_of(frame) == title:
            return frame
    if len(same_pid) == 1:
        return same_pid[0]
    titled = [frame for _, frame in candidates if title and name_of(frame) == title]
    if len(titled) == 1:
        return titled[0]
    return same_pid[0] if same_pid else None


def tree(frame, table: RefTable) -> tuple[SnapNode, int]:
    """The frame's tree as snapshot nodes, refs on the controls, and how many elements were read."""
    count = 0

    def node(element, depth: int) -> SnapNode:
        nonlocal count
        count += 1
        role = role_of(element)
        name = name_of(element)
        value = text_of(element) if role in ("edit", "combobox", "spinner", "document") else None
        made = SnapNode(role=role, name=name, value=value, states=states_of(element))
        if role in CONTROLS and _has(element, Atspi.StateType.VISIBLE):
            made.ref = table.add(element)
        if depth < DEEPEST:
            for child in children(element):
                if count >= MOST_NODES:
                    break
                if _has(child, Atspi.StateType.SHOWING) or role_of(child) in ("menuitem",):
                    made.children.append(node(child, depth + 1))
        return made

    return node(frame, 0), count


def extents(element) -> tuple[int, int, int, int] | None:
    """Where the element is on the screen, or None when it does not say."""
    try:
        box = element.get_extents(Atspi.CoordType.SCREEN)
    except Exception:
        return None
    if box.width <= 0 or box.height <= 0:
        return None
    return box.x, box.y, box.width, box.height


def grab_focus(element) -> bool:
    try:
        return bool(element.grab_focus())
    except Exception:
        return False


def activate(element) -> bool:
    """Its first action - press, click, activate - for an element that has no place on the screen to click."""
    try:
        action = element.get_action_iface()
        if action is not None and action.get_n_actions() > 0:
            return bool(action.do_action(0))
    except Exception:
        pass
    return False
