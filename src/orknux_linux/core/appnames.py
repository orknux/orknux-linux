"""Which installed app a person means by the name they would type into the app menu.

The same rules as Orknux for Windows' AppNames: the whole name first, then a
name starting with it, then one with it as a word, then anywhere; never an
uninstaller or a readme when the app itself is there. And a running program is
the app only by its own name, or that name with a version after it - so asking
for "gedit" never decides it is running because "gedit-plugins" is.
"""

INCIDENTAL = ("uninstall", "setup", "readme", "help", "documentation", "release notes", "website", "license", "repair")
NOT_FOUND = 1 << 30


def normal(text: str) -> str:
    trimmed = text.strip()
    for ending in (".desktop", ".lnk", ".exe", ".appref-ms"):
        if trimmed.lower().endswith(ending):
            trimmed = trimmed[: -len(ending)]
    for separator in ("\t", "_", "-"):
        trimmed = trimmed.replace(separator, " ")
    return " ".join(trimmed.lower().split())


def _rank(wanted: str, name: str) -> int:
    if not name:
        return NOT_FOUND
    penalty = 10 if any(word in name and word not in wanted for word in INCIDENTAL) else 0
    if name == wanted:
        return 0 + penalty
    if name.startswith(wanted):
        return 1 + penalty
    if f" {wanted} " in f" {name} ":
        return 2 + penalty
    if wanted in name:
        return 3 + penalty
    return NOT_FOUND


def best(asked: str, names) -> str | None:
    """The best of names for what was asked, or None when none contains it."""
    wanted = normal(asked)
    if not wanted:
        return None
    ranked = [(rank, len(name), name.lower(), name) for name in names if (rank := _rank(wanted, normal(name))) < NOT_FOUND]
    return min(ranked)[3] if ranked else None


def near(asked: str, names, most: int = 5) -> list[str]:
    """A few names sharing a word with what was asked, for saying what there is when nothing matched."""
    words = [word for word in normal(asked).split(" ") if len(word) >= 3]
    seen: dict[str, str] = {}
    for name in names:
        if any(word[:4] in normal(name) for word in words):
            seen.setdefault(name.lower(), name)
    return sorted(seen.values(), key=len)[:most]


def is_program(asked: str, program: str | None) -> bool:
    """Whether a running program, by its process name, is the app asked for."""
    if not program or not program.strip():
        return False
    wanted = normal(asked).replace(" ", "")
    running = normal(program).replace(" ", "")
    if not wanted:
        return False
    return running == wanted or (running.startswith(wanted) and running[len(wanted):].isdigit())
