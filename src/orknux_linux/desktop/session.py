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
