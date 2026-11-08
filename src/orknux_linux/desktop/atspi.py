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


def _implements(element, interface: str) -> bool:
    try:
        return interface in (element.get_interfaces() or [])
    except Exception:
        return False


# Every interface is called as Atspi.Text.get_text(element, ...), never through get_text_iface(): from
# libatspi 2.5x the iface getters hand back the element itself, whose own get_text() is a deprecated method
# with another signature, so the old spelling failed - silently, as nothing but None - on current desktops.
def text_of(element) -> str | None:
    if not _implements(element, "Text"):
        return None
    try:
        return Atspi.Text.get_text(element, 0, Atspi.Text.get_character_count(element))
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
        box = Atspi.Component.get_extents(element, Atspi.CoordType.SCREEN)
    except Exception:
        return None
    if box.width <= 0 or box.height <= 0:
        return None
    return box.x, box.y, box.width, box.height


def grab_focus(element) -> bool:
    try:
        return _implements(element, "Component") and bool(Atspi.Component.grab_focus(element))
    except Exception:
        return False


def activate(element) -> bool:
    """Its first action - press, click, activate - for an element that has no place on the screen to click."""
    if not _implements(element, "Action"):
        return False
    try:
        return Atspi.Action.get_n_actions(element) > 0 and bool(Atspi.Action.do_action(element, 0))
    except Exception:
        return False


# ---- what Wayland needs: acting on a control through accessibility rather than through input ----

def has_state(element, name: str) -> bool:
    return _has(element, getattr(Atspi.StateType, name))


def frames_by_key():
    """Every top-level frame with a key that stays the same while it lives: its process and its object path."""
    for pid, frame in frames():
        try:
            path = frame.path
        except Exception:
            path = None
        yield (pid, path or name_of(frame)), pid, frame


# The action a click on a control means, by the names toolkits give it, in order of preference.
CLICK_ACTIONS = ("click", "press", "activate", "jump", "toggle", "open", "select")
MENU_ACTIONS = ("show menu", "showmenu", "menu", "context menu")


def actions_of(element) -> list[str]:
    if not _implements(element, "Action"):
        return []
    try:
        return [(Atspi.Action.get_action_name(element, i) or "").lower() for i in range(Atspi.Action.get_n_actions(element))]
    except Exception:
        return []


def do_action(element, wanted: tuple[str, ...]) -> str | None:
    """Does the first of [wanted] the element offers, or its first action when it names none of them; which, or None."""
    names = actions_of(element)
    if not names:
        return None
    index = next((names.index(w) for w in wanted if w in names), None)
    if index is None:
        if wanted is MENU_ACTIONS:
            return None
        index = 0
    try:
        return names[index] if Atspi.Action.do_action(element, index) else None
    except Exception:
        return None


def set_text(element, text: str, append: bool) -> bool:
    """Replaces or extends what a field holds, through its EditableText, and checks it took."""
    if not _implements(element, "EditableText"):
        return False
    before = text_of(element) or ""
    try:
        if append:
            done = Atspi.EditableText.insert_text(element, len(before), text, len(text.encode("utf-8")))
        else:
            done = Atspi.EditableText.set_text_contents(element, text)
    except Exception:
        return False
    after = text_of(element)
    expected = before + text if append else text
    return bool(done) and after == expected


def walk(element, depth: int = 12):
    yield element
    if depth <= 0:
        return
    for child in children(element):
        yield from walk(child, depth - 1)


def scroll_bars(element) -> list:
    return [e for e in walk(element) if role_of(e) == "scrollbar"]


def scroll_by_value(element, vertical: bool, notches: int) -> bool:
    """Moves the first scroll bar in [element] that runs the right way by [notches] steps; whether one moved."""
    for bar in scroll_bars(element):
        horizontal = has_state(bar, "HORIZONTAL")
        if horizontal == vertical:
            continue
        if not _implements(bar, "Value"):
            continue
        try:
            low, high = Atspi.Value.get_minimum_value(bar), Atspi.Value.get_maximum_value(bar)
            now = Atspi.Value.get_current_value(bar)
            step = Atspi.Value.get_minimum_increment(bar) or 0
            if step <= 0:
                step = max((high - low) / 20, 1)
            return bool(Atspi.Value.set_current_value(bar, max(low, min(high, now + notches * step * 3))))
        except Exception:
            continue
    return False


CLOSE_NAMES = {"close", "zamknij", "schließen", "fermer", "cerrar", "chiudi", "fechar", "закрыть", "sluiten"}


def close_button(frame):
    """The window's own Close button, where its toolkit draws one (GTK's header bar, libadwaita)."""
    for element in walk(frame, 8):
        if role_of(element) == "button" and name_of(element).strip().lower() in CLOSE_NAMES:
            return element
    return None


def enable_accessibility() -> bool | None:
    """
    Asks every program started from now on to publish what it shows, as a
    screen reader does; most do not unless asked. The value it had before,
    so it can be put back, or None when the bus could not be reached.
    """
    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync("org.a11y.Bus", "/org/a11y/bus", "org.freedesktop.DBus.Properties", "Get",
                              GLib.Variant("(ss)", ("org.a11y.Status", "IsEnabled")), None, Gio.DBusCallFlags.NONE, 2000, None)
        was = bool(reply.unpack()[0])
        if not was:
            set_accessibility(True)
        return was
    except Exception:
        return None


def set_accessibility(on: bool):
    from gi.repository import Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    bus.call_sync("org.a11y.Bus", "/org/a11y/bus", "org.freedesktop.DBus.Properties", "Set",
                  GLib.Variant("(ssv)", ("org.a11y.Status", "IsEnabled", GLib.Variant("b", on))), None,
                  Gio.DBusCallFlags.NONE, 2000, None)


def insert_at_caret(element, text: str) -> bool:
    """
    Types [text] where the caret is, through accessibility, replacing what is
    selected as a keystroke would; whether the field now holds it.
    """
    if not (_implements(element, "EditableText") and _implements(element, "Text")):
        return False
    try:
        if Atspi.Text.get_n_selections(element) > 0:
            chosen = Atspi.Text.get_selection(element, 0)
            if chosen.end_offset > chosen.start_offset:
                Atspi.EditableText.delete_text(element, chosen.start_offset, chosen.end_offset)
        caret = max(0, Atspi.Text.get_caret_offset(element))
        before = text_of(element) or ""
        if not Atspi.EditableText.insert_text(element, caret, text, len(text.encode("utf-8"))):
            return False
        Atspi.Text.set_caret_offset(element, caret + len(text))
        return (text_of(element) or "") == before[:caret] + text + before[caret:]
    except Exception:
        return False
