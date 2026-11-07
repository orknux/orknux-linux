"""Pasting text a keyboard cannot be trusted with, and giving the person's clipboard back.

XTest types a key, and a key types whatever the keyboard layout says it does:
a letter past ASCII - ą, ż, ń - is on no key of a US layout and on a different
one in every other. So, as on Windows, such text is put on the clipboard and
pasted with Ctrl+V, one event the control takes whole, and the clipboard's text
is put back afterwards. Only its text: xclip serves one type at a time, so an
image someone had copied is not restored, and that is said where it is used.
"""

import shutil
import subprocess
import time


def needed(text: str) -> bool:
    """Whether text is better pasted than typed: anything a US keyboard would not type as it is."""
    return any(ord(unit) > 0x7E or (ord(unit) < 0x20 and unit not in "\n\t") for unit in text)


def available() -> bool:
    return shutil.which("xclip") is not None


def read() -> str | None:
    try:
        held = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return held.stdout.decode("utf-8", "replace") if held.returncode == 0 else None


def write(text: str):
    # xclip stays behind to serve the selection until somebody else owns it, as a person's copy would.
    subprocess.run(["xclip", "-selection", "clipboard", "-i"], input=text.encode("utf-8"), timeout=3,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def paste(text: str, press_paste):
    """Puts text where the focus is through the clipboard, then puts back what the clipboard held."""
    kept = read()
    write(text)
    time.sleep(0.05)
    press_paste()
    # The target reads the clipboard when it handles the paste, which is not the moment the keys go in.
    time.sleep(0.3)
    write(kept if kept is not None else "")
