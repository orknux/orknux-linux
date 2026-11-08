"""The half that touches the desktop: X11 for windows, input and pictures, AT-SPI for what is in them."""

# python-xlib, and the six it needs, come with Orknux for Linux (_vendor, with their licences), for an X11
# desktop where the distribution's package is not installed: pure Python, so nothing for the person to install.
# Put after everything else on the path, so a copy the system has is the one used.
import importlib.util as _util
import os as _os
import sys as _sys

if _util.find_spec("Xlib") is None or _util.find_spec("six") is None:
    _sys.path.append(_os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "_vendor"))
