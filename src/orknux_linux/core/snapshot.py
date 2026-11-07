"""A window's accessibility tree as the text an agent reads, with [eN] refs on what it can act on.

The same rendering as Orknux for Windows' SnapshotRenderer, so desktop_snapshot
reads alike on both: a ref and a role for each control, its name and value,
its states; text and images under no control as plain lines; headings named.
"""

from dataclasses import dataclass, field

from .errors import Refused

LONGEST_TEXT = 300

CONTROLS = {
    "button", "edit", "combobox", "checkbox", "radiobutton", "hyperlink", "listitem", "menuitem",
    "tabitem", "treeitem", "slider", "spinner", "splitbutton", "dataitem", "menubar", "scrollbar",
    "document", "headeritem",
}


@dataclass
class SnapNode:
    role: str
    name: str = ""
    value: str | None = None
    states: list[str] = field(default_factory=list)
    ref: str | None = None
    children: list["SnapNode"] = field(default_factory=list)


class RefTable:
    """The controls of one snapshot by ref: e1, e2, ... in the order they were met."""

    def __init__(self):
        self._by_ref: dict[str, object] = {}

    def add(self, element) -> str:
        name = f"e{len(self._by_ref) + 1}"
        self._by_ref[name] = element
        return name

    def resolve(self, reference: str | None):
        text = (reference or "").strip().lower()
        if not text:
            raise Refused("Give the control's ref from desktop_snapshot, like e12.")
        if text not in self._by_ref:
            raise Refused(f'"{text}" is not a ref in the latest snapshot of this window. Take a fresh desktop_snapshot.')
        return self._by_ref[text]

    def __len__(self) -> int:
        return len(self._by_ref)


def _flat(value: str | None) -> str:
    return " ".join((value or "").split())


def _cut(text: str) -> str:
    return text[:LONGEST_TEXT] + "…" if len(text) > LONGEST_TEXT else text


def _quoted(text: str) -> str:
    return '"' + _cut(text).replace('"', '\\"') + '"'


def lines_of(root: SnapNode, interactive_only: bool) -> list[str]:
    lines: list[str] = []

    def visit(node: SnapNode, quiet: bool):
        hush = quiet
        name = _flat(node.name)
        role = node.role.lower()
        if node.ref is not None:
            line = f"[{node.ref}] {role}"
            if name:
                line += " " + _quoted(name)
            value = _flat(node.value)
            if value and value != name:
                line += " value=" + _quoted(value)
            if node.states:
                line += " (" + ", ".join(node.states) + ")"
            lines.append(line)
            hush = True
        elif not interactive_only and not quiet and name and role in ("text", "image"):
            lines.append("image " + _quoted(name) if role == "image" else _cut(name))
        elif not interactive_only and name and role == "header":
            lines.append("heading " + _quoted(name))
            hush = True
        for child in node.children:
            visit(child, hush)

    visit(root, False)
    return lines


def render(window: int, title: str, lines: list[str], find: str | None, max_characters: int) -> dict:
    shown = [line for line in lines if find.lower() in line.lower()] if find else lines
    text = f"Window: {title or '(untitled)'}\nId: {window}\n"
    kept = 0
    for line in shown:
        if len(text) + len(line) + 1 > max_characters:
            break
        text += line + "\n"
        kept += 1
    result: dict = {"window": window, "title": title, "text": text}
    if kept < len(shown):
        result["cut"] = f"{len(shown) - kept} more lines were cut. Ask for a part with find, take interactiveOnly, or scroll."
    if find and not shown:
        result["note"] = f'Nothing in the window contains "{find}".'
    return result
