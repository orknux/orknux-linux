"""The desktop through X11: the windows the window manager lists, input as XTest, pictures off the screen.

EWMH is how windows are named, found, brought forward and closed - what every
mainstream window manager answers - so nothing here depends on wmctrl or
xdotool being installed. Input goes through XTest, which X applications cannot
tell from a person's keyboard and mouse.
"""

import os
import threading
import time

from Xlib import X, XK, display
from Xlib.error import XError
from Xlib.ext import xtest
from Xlib.protocol import event

from ..core.connection import wait_for
from ..core.keychord import PUNCTUATION

# How long a window is given to come forward, and to settle once it has.
FOREGROUND_WAIT = 1.0
ACTIVATED = 0.12
SETTLE = 0.15


class X11:
    def __init__(self, name: str | None = None):
        self.d = display.Display(name)
        self.root = self.d.screen().root
        self._lock = threading.RLock()

    # ---- atoms and properties ----

    def _atom(self, name: str) -> int:
        return self.d.intern_atom(name)

    def _prop(self, window, name: str, kind=X.AnyPropertyType):
        try:
            value = window.get_full_property(self._atom(name), kind)
        except XError:
            return None
        return value.value if value is not None else None

    def _window(self, wid: int):
        return self.d.create_resource_object("window", wid)

    # ---- the windows ----

    def client_list(self) -> list[int]:
        with self._lock:
            ids = self._prop(self.root, "_NET_CLIENT_LIST") or []
            return [int(w) for w in ids]

    def active(self) -> int | None:
        with self._lock:
            value = self._prop(self.root, "_NET_ACTIVE_WINDOW")
            return int(value[0]) if value is not None and len(value) and value[0] else None

    def title(self, wid: int) -> str:
        with self._lock:
            window = self._window(wid)
            raw = self._prop(window, "_NET_WM_NAME", self._atom("UTF8_STRING"))
            if raw:
                return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            try:
                name = window.get_wm_name()
            except XError:
                name = None
            return name.decode("latin-1") if isinstance(name, bytes) else (name or "")

    def pid(self, wid: int) -> int | None:
        with self._lock:
            value = self._prop(self._window(wid), "_NET_WM_PID")
            return int(value[0]) if value is not None and len(value) else None

    def minimized(self, wid: int) -> bool:
        with self._lock:
            states = self._prop(self._window(wid), "_NET_WM_STATE") or []
            return self._atom("_NET_WM_STATE_HIDDEN") in list(states)

    def exists(self, wid: int) -> bool:
        return wid in self.client_list()

    def geometry(self, wid: int) -> tuple[int, int, int, int]:
        """The window's content on the screen: x, y, width, height."""
        with self._lock:
            window = self._window(wid)
            size = window.get_geometry()
            at = self.root.translate_coords(window, 0, 0)
            return at.x, at.y, size.width, size.height

    def screen_size(self) -> tuple[int, int]:
        screen = self.d.screen()
        return screen.width_in_pixels, screen.height_in_pixels

    # ---- acting on windows ----

    def _client_message(self, wid: int, kind: str, data: list[int]):
        message = event.ClientMessage(window=self._window(wid), client_type=self._atom(kind), data=(32, (data + [0] * 5)[:5]))
        self.root.send_event(message, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
        self.d.flush()

    def front(self, wid: int) -> bool:
        """
        Brings a window forward and gives it the focus, restoring it if minimised,
        and says whether it ended up in front. Waits for the window manager to say
        so, then a moment more for the window to focus its own control: keys sent
        at once go to the window before it.
        """
        with self._lock:
            # Source 2: asked for by a pager, which a window manager honours where it may refuse an application.
            self._client_message(wid, "_NET_ACTIVE_WINDOW", [2, X.CurrentTime, 0])
            try:
                window = self._window(wid)
                window.map()
                window.configure(stack_mode=X.Above)
                self.d.flush()
            except XError:
                pass
        came = wait_for(lambda: self.active() == wid, FOREGROUND_WAIT, 0.025)
        if not came:
            with self._lock:
                try:
                    self._window(wid).set_input_focus(X.RevertToParent, X.CurrentTime)
                    self.d.flush()
                except XError:
                    pass
            came = wait_for(lambda: self.active() == wid, FOREGROUND_WAIT / 2, 0.025)
        time.sleep(ACTIVATED)
        return self.active() == wid

    def close(self, wid: int):
        with self._lock:
            self._client_message(wid, "_NET_CLOSE_WINDOW", [X.CurrentTime, 2])

    # ---- pictures ----

    def capture(self, x: int, y: int, width: int, height: int):
        """A part of the screen as a Pillow image, clipped to the screen."""
        from PIL import Image

        screen_w, screen_h = self.screen_size()
        left, top = max(0, x), max(0, y)
        right, bottom = min(screen_w, x + width), min(screen_h, y + height)
        if right <= left or bottom <= top:
            raise ValueError("the window is off the screen")
        with self._lock:
            raw = self.root.get_image(left, top, right - left, bottom - top, X.ZPixmap, 0xFFFFFFFF)
        return Image.frombytes("RGB", (right - left, bottom - top), raw.data, "raw", "BGRX")

    # ---- input ----

    def settle(self):
        with self._lock:
            self.d.sync()
        time.sleep(SETTLE)

    def move(self, x: int, y: int):
        with self._lock:
            xtest.fake_input(self.d, X.MotionNotify, x=int(x), y=int(y))
            self.d.sync()

    def click(self, x: int, y: int, button: int = 1, double: bool = False):
        self.move(x, y)
        with self._lock:
            for _ in range(2 if double else 1):
                xtest.fake_input(self.d, X.ButtonPress, button)
                xtest.fake_input(self.d, X.ButtonRelease, button)
                self.d.sync()
                time.sleep(0.05)

    def scroll(self, x: int, y: int, direction: str, notches: int):
        button = {"up": 4, "down": 5, "left": 6, "right": 7}[direction]
        self.move(x, y)
        with self._lock:
            for _ in range(notches):
                xtest.fake_input(self.d, X.ButtonPress, button)
                xtest.fake_input(self.d, X.ButtonRelease, button)
            self.d.sync()

    def _keycode(self, keysym_name: str) -> tuple[int, bool]:
        """The key that types a keysym, and whether Shift must be held for it."""
        keysym = XK.string_to_keysym(keysym_name)
        if keysym == 0:
            raise ValueError(f"no keysym {keysym_name}")
        keycode = self.d.keysym_to_keycode(keysym)
        if keycode == 0:
            raise ValueError(f"no key types {keysym_name} on this keyboard")
        shifted = self.d.keycode_to_keysym(keycode, 0) != keysym and self.d.keycode_to_keysym(keycode, 1) == keysym
        return keycode, shifted

    def chord(self, keysym_names: list[str]):
        """Presses the keys together, modifiers first, and lets them go in reverse."""
        with self._lock:
            codes = [self._keycode(name)[0] for name in keysym_names]
            for code in codes:
                xtest.fake_input(self.d, X.KeyPress, code)
            for code in reversed(codes):
                xtest.fake_input(self.d, X.KeyRelease, code)
            self.d.sync()

    def type_ascii(self, text: str, gap: float = 0.008):
        """
        Types plain ASCII key by key, a few milliseconds apart: a person types
        slower than this, and every editor keeps up with a person.
        """
        shift = self._keycode("Shift_L")[0]
        for char in text:
            name = {"\n": "Return", "\t": "Tab"}.get(char) or PUNCTUATION.get(char) or char
            code, shifted = self._keycode(name)
            with self._lock:
                if shifted:
                    xtest.fake_input(self.d, X.KeyPress, shift)
                xtest.fake_input(self.d, X.KeyPress, code)
                xtest.fake_input(self.d, X.KeyRelease, code)
                if shifted:
                    xtest.fake_input(self.d, X.KeyRelease, shift)
                self.d.sync()
            time.sleep(gap)


class StopHotkey:
    """
    Ctrl+Alt+Q, wherever the focus is: the one way to stop an agent mid-action
    without finding this window. Grabbed on the root window with every lock-key
    combination, so Caps Lock or Num Lock being on does not hide it.
    """

    def __init__(self, on_press, name: str | None = None):
        self.on_press = on_press
        self.d = display.Display(name)
        self.root = self.d.screen().root
        self.keycode = self.d.keysym_to_keycode(XK.string_to_keysym("q"))
        base = X.ControlMask | X.Mod1Mask
        for extra in (0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask):
            self.root.grab_key(self.keycode, base | extra, True, X.GrabModeAsync, X.GrabModeAsync)
        self.d.sync()
        threading.Thread(target=self._listen, daemon=True, name="stop-hotkey").start()

    def _listen(self):
        while True:
            try:
                happened = self.d.next_event()
            except Exception:
                return
            if happened.type == X.KeyPress and happened.detail == self.keycode:
                self.on_press()


def session_is_wayland() -> bool:
    """A Wayland session, where X11 input reaches only XWayland windows and so is not offered at all."""
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or (
        bool(os.environ.get("WAYLAND_DISPLAY")) and not os.environ.get("ORKNUX_FORCE_X11"))
