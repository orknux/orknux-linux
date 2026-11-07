"""A key, or a combination like Ctrl+Shift+S, written the way a model writes one.

The same vocabulary as Orknux for Windows' KeyChord, so one agent prompt works
on both: Ctrl, Shift, Alt and Win as modifiers, one character or a named key
last. Here each part also has the X11 keysym it is pressed as.
"""

from dataclasses import dataclass

from .errors import Refused

MODIFIERS = {
    "ctrl": "Ctrl", "control": "Ctrl",
    "shift": "Shift",
    "alt": "Alt", "option": "Alt",
    "win": "Win", "windows": "Win", "meta": "Win", "cmd": "Win", "super": "Win",
}

MODIFIER_KEYSYMS = {"Ctrl": "Control_L", "Shift": "Shift_L", "Alt": "Alt_L", "Win": "Super_L"}

NAMED = ["Enter", "Tab", "Escape", "Backspace", "Delete", "Insert", "Space",
         "Up", "Down", "Left", "Right", "PageUp", "PageDown", "Home", "End",
         "PrintScreen", "Menu"] + [f"F{n}" for n in range(1, 25)]

ALIASES = {
    "return": "Enter", "esc": "Escape", "del": "Delete", "ins": "Insert",
    "arrowup": "Up", "arrowdown": "Down", "arrowleft": "Left", "arrowright": "Right",
    "pgup": "PageUp", "pgdn": "PageDown", "spacebar": "Space",
}

KEYSYMS = {
    "Enter": "Return", "Tab": "Tab", "Escape": "Escape", "Backspace": "BackSpace", "Delete": "Delete",
    "Insert": "Insert", "Space": "space", "Up": "Up", "Down": "Down", "Left": "Left", "Right": "Right",
    "PageUp": "Prior", "PageDown": "Next", "Home": "Home", "End": "End", "PrintScreen": "Print", "Menu": "Menu",
    **{f"F{n}": f"F{n}" for n in range(1, 25)},
}

# A character typed as itself on a key: the punctuation X11 names rather than spells.
PUNCTUATION = {
    " ": "space", "+": "plus", "-": "minus", "=": "equal", ",": "comma", ".": "period", "/": "slash",
    "\\": "backslash", ";": "semicolon", "'": "apostrophe", "`": "grave", "[": "bracketleft", "]": "bracketright",
    "!": "exclam", "@": "at", "#": "numbersign", "$": "dollar", "%": "percent", "^": "asciicircum", "&": "ampersand",
    "*": "asterisk", "(": "parenleft", ")": "parenright", "_": "underscore", "{": "braceleft", "}": "braceright",
    "|": "bar", ":": "colon", "\"": "quotedbl", "<": "less", ">": "greater", "?": "question", "~": "asciitilde",
}


@dataclass(frozen=True)
class KeyChord:
    modifiers: tuple[str, ...]
    key: str

    def __str__(self) -> str:
        return "+".join((*self.modifiers, self.key))

    def keysyms(self) -> list[str]:
        """Each part's keysym name, modifiers first, as they are pressed."""
        return [MODIFIER_KEYSYMS[m] for m in self.modifiers] + [keysym_of(self.key)]


def keysym_of(key: str) -> str:
    if key in KEYSYMS:
        return KEYSYMS[key]
    if key in MODIFIER_KEYSYMS:
        return MODIFIER_KEYSYMS[key]
    if len(key) == 1:
        if key.isalpha():
            return key.lower()
        if key.isdigit():
            return key
        if key in PUNCTUATION:
            return PUNCTUATION[key]
    raise Refused(f'"{key}" is not a key this knows.')


def parse(written: str | None) -> KeyChord:
    text = (written or "").strip()
    if not text:
        raise Refused("Say which key to press, like Enter or Ctrl+S.")
    parts = [part.strip() for part in text.split("+") if part != ""]
    # "+" alone, or a chord ending in "+" ("Ctrl++"), is the plus key.
    if text.endswith("+"):
        parts.append("+")
    if not parts:
        raise Refused(f'"{text}" is not a key.')
    modifiers: list[str] = []
    for part in parts[:-1]:
        modifier = MODIFIERS.get(part.lower())
        if modifier is None:
            raise Refused(f'"{part}" is not a modifier. Use Ctrl, Shift, Alt or Win, joined with + like Ctrl+Shift+S.')
        if modifier not in modifiers:
            modifiers.append(modifier)
    last = parts[-1]
    named = {n.lower(): n for n in NAMED}
    if last.lower() in named:
        key = named[last.lower()]
    elif last.lower() in ALIASES:
        key = ALIASES[last.lower()]
    elif len(last) == 1:
        key = last.upper() if last.isalpha() else last
    elif last.lower() in MODIFIERS and not modifiers:
        key = MODIFIERS[last.lower()]
    else:
        raise Refused(
            f'"{last}" is not a key this knows. Use one character, a name like Enter, Tab, Escape, an arrow, '
            "PageUp or F5, or a combination like Ctrl+S.")
    return KeyChord(tuple(modifiers), key)
