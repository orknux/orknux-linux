"""Which kind of desktop this is, known without loading either's libraries."""

import os


def session_is_wayland() -> bool:
    """
    A Wayland session, driven through the portals: X11 input there reaches
    only XWayland windows. ORKNUX_FORCE_X11 says otherwise, for a test.
    """
    if os.environ.get("ORKNUX_FORCE_X11"):
        return False
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))


def forwarded_over_ssh() -> bool:
    """
    Started in an SSH session with X forwarding: the window shows on another
    computer, and the display it would drive is that computer's X server - not
    this computer's desktop, which an agent is meant to use.
    """
    display = os.environ.get("DISPLAY", "")
    return bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT")) and \
        display.split(":")[0] not in ("", "unix") and not os.environ.get("WAYLAND_DISPLAY")


SSH_WARNING = ("This was started over SSH, with the window forwarded to another computer: the desktop an agent would "
               "use is that computer's display, not this one's. Start Orknux for Linux on this computer's own desktop "
               "- from a terminal there, or from its app menu.")
