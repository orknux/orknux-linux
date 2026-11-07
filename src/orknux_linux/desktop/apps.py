"""The apps the desktop's app menu offers, by name: its .desktop entries.

Read when a bare name is not a program on the PATH, as Orknux for Windows reads
the Start menu: "libreoffice writer" or "musescore" finds the entry and starts
what it says to start.
"""

import configparser
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from ..core import appnames


def _dirs() -> list[Path]:
    home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    data = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    roots = [home] + [Path(d) for d in data.split(":") if d]
    roots += [Path("/var/lib/flatpak/exports/share"), Path.home() / ".local/share/flatpak/exports/share",
              Path("/var/lib/snapd/desktop")]
    return [root / "applications" for root in roots]


def entries() -> dict[str, Path]:
    """Name to .desktop file, the first one found winning as XDG says the user's own do."""
    found: dict[str, Path] = {}
    for folder in _dirs():
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.desktop")):
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                parser.read(path, encoding="utf-8")
                entry = parser["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            if entry.get("Type", "Application") != "Application" or entry.get("NoDisplay") == "true" or entry.get("Hidden") == "true":
                continue
            name = entry.get("Name")
            if name and entry.get("Exec"):
                found.setdefault(name, path)
    return found


def find(asked: str) -> tuple[tuple[str, Path] | None, list[str]]:
    """The entry a person means, or None and the closest names there are."""
    known = entries()
    best = appnames.best(asked, known.keys())
    if best is not None:
        return (best, known[best]), []
    return None, appnames.near(asked, known.keys())


def launch(path: Path, arguments: list[str]) -> subprocess.Popen | None:
    """Starts a .desktop entry: through gio where it is installed, else its Exec line with the field codes taken out."""
    if not arguments and shutil.which("gio"):
        return subprocess.Popen(["gio", "launch", str(path)], start_new_session=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read(path, encoding="utf-8")
    command = [part for part in shlex.split(parser["Desktop Entry"]["Exec"]) if not (len(part) == 2 and part.startswith("%"))]
    return subprocess.Popen(command + arguments, start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
