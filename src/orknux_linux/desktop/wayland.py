"""The desktop on Wayland: windows through AT-SPI, input and pictures through the portals.

The same methods as X11, so the runner drives either. What Wayland does not
allow is said rather than faked:

- No program learns where another's window is, so `positions` is False and the
  runner acts on a control through accessibility - presses it with its own
  action, sets its text - instead of at a point. A point a model read off a
  whole-screen picture can still be clicked: the pointer is placed through the
  RemoteDesktop portal against the monitors ScreenCast reports.
- GNOME raises no window at another program's request, so `front` does what
  a person does: clicks the app's button in the dock or the overview with the
  portal's pointer, and answers whether the window really came.
- A window's picture is the whole screen: the Screenshot portal takes nothing
  smaller without asking the person to choose.
"""

import os
import threading
import time

import gi

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk  # noqa: E402

from ..core.connection import wait_for  # noqa: E402
from ..core.errors import Refused  # noqa: E402
from . import atspi  # noqa: E402
from .portal import Portal, RemoteControl, screenshot_file  # noqa: E402

SETTLE = 0.2
OVERVIEW_WAIT = 0.8
FOREGROUND_WAIT = 1.2
KEY_GAP = 0.006


class Wayland:
    positions = False

    def __init__(self, token: str | None = None, save_token=lambda token: None, portal: Portal | None = None):
        self.portal = portal or Portal()
        self.remote = RemoteControl(self.portal, token, save_token)
        self._ids: dict[tuple, int] = {}
        self._frames: dict[int, tuple[int | None, object]] = {}
        self._next = 1
        self._lock = threading.RLock()

    # ---- the windows ----

    def _refresh(self) -> list[int]:
        with self._lock:
            seen = []
            frames = {}
            for key, pid, frame in atspi.frames_by_key():
                if self._is_shell(frame):
                    continue
                wid = self._ids.get(key)
                if wid is None:
                    wid = self._ids[key] = self._next
                    self._next += 1
                frames[wid] = (pid, frame)
                seen.append(wid)
            self._frames = frames
            return seen

    @staticmethod
    def _is_shell(frame) -> bool:
        """The desktop's own stage - GNOME Shell's panel, dash and dialogs - which is not one of the person's windows."""
        try:
            return frame.get_application().get_toolkit_name() in ("clutter", "St") or atspi.name_of(frame) == "Main stage"
        except Exception:
            return atspi.name_of(frame) == "Main stage"

    @staticmethod
    def _shell_stage():
        for _pid, frame in atspi.frames():
            if Wayland._is_shell(frame):
                return frame
        return None

    def client_list(self) -> list[int]:
        return self._refresh()

    def frame(self, wid: int):
        if wid not in self._frames:
            self._refresh()
        entry = self._frames.get(wid)
        return entry[1] if entry else None

    def active(self) -> int | None:
        for wid in self._refresh():
            if atspi.has_state(self._frames[wid][1], "ACTIVE"):
                return wid
        return None

    def title(self, wid: int) -> str:
        frame = self.frame(wid)
        return atspi.name_of(frame) if frame is not None else ""

    def pid(self, wid: int) -> int | None:
        if wid not in self._frames:
            self._refresh()
        entry = self._frames.get(wid)
        return entry[0] if entry else None

    def minimized(self, wid: int) -> bool:
        frame = self.frame(wid)
        return frame is not None and atspi.has_state(frame, "ICONIFIED")

    def exists(self, wid: int) -> bool:
        return wid in self._refresh()

    def geometry(self, wid: int):
        return None

    def screen_size(self) -> tuple[int, int]:
        bounds = self.remote.bounds()
        if bounds:
            return bounds[2], bounds[3]
        return self._monitors()[2:]

    @staticmethod
    def _monitors() -> tuple[int, int, int, int]:
        display = Gdk.Display.get_default() or Gdk.Display.open(os.environ.get("WAYLAND_DISPLAY"))
        boxes = [display.get_monitor(i).get_geometry() for i in range(display.get_n_monitors())]
        left, top = min(b.x for b in boxes), min(b.y for b in boxes)
        return left, top, max(b.x + b.width for b in boxes) - left, max(b.y + b.height for b in boxes) - top

    # ---- acting on windows ----

    def front(self, wid: int) -> bool:
        """
        Brings a window forward the way a person would on GNOME: its app's button
        in the dock or the dash, clicked with the portal's pointer - the overview
        opened first where no such button is showing. GNOME raises no window at
        another program's request, so this is the way in. True only where the
        window really became the active one; with several windows of one app,
        the app's last used one is what comes.
        """
        frame = self.frame(wid)
        if frame is None:
            return False
        if atspi.has_state(frame, "ACTIVE"):
            return True
        names = self._app_names(wid, frame)
        if not self._click_launcher(names):
            self.chord(["Super_L"])
            time.sleep(OVERVIEW_WAIT)
            if not self._click_launcher(names):
                self.chord(["Escape"])
                return False
        came = wait_for(lambda: atspi.has_state(frame, "ACTIVE"), FOREGROUND_WAIT, 0.05)
        time.sleep(0.15)
        return came

    def _app_names(self, wid: int, frame) -> set[str]:
        names = set()
        try:
            names.add(frame.get_application().get_name())
        except Exception:
            pass
        from .runner import program_of

        names.add(program_of(self.pid(wid)))
        title = atspi.name_of(frame)
        if " - " in title or " — " in title:
            names.add(title.replace(" — ", " - ").rsplit(" - ", 1)[-1])
        return {n.strip().lower() for n in names if n and n.strip()}

    def _click_launcher(self, names: set[str]) -> bool:
        stage = self._shell_stage()
        if stage is None or not names:
            return False
        for element in atspi.walk(stage, 30):
            if atspi.role_of(element) != "button" or not atspi.has_state(element, "SHOWING"):
                continue
            said = atspi.name_of(element).strip().lower()
            if not said or not (said in names or any(n in said or said in n for n in names if len(n) > 3)):
                continue
            box = atspi.extents(element)  # the shell's own elements are placed on the real screen
            if box is None:
                continue
            x, y, width, height = box
            self.click(x + width // 2, y + height // 2)
            return True
        return False

    def close(self, wid: int):
        frame = self.frame(wid)
        if frame is None:
            return
        button = atspi.close_button(frame)
        if button is not None and atspi.do_action(button, atspi.CLICK_ACTIONS):
            return
        if not self.front(wid):
            raise Refused("This window has no Close button to press, and the desktop did not let it come to the "
                          "front for Alt+F4. Ask the person to close it, or bring it forward first.")
        self.chord(["Alt_L", "F4"])

    # ---- pictures ----

    def capture(self, x: int = 0, y: int = 0, width: int = 0, height: int = 0):
        """The whole screen, at the size of the coordinates a click takes, whatever the monitors' scale."""
        from PIL import Image

        cast = self.remote.picture()
        if cast is not None:
            return cast
        path = screenshot_file(self.portal)
        try:
            with Image.open(path) as taken:
                image = taken.convert("RGB")
        finally:
            # The desktop keeps every portal screenshot in Pictures; this one was the agent's, not the person's.
            try:
                os.remove(path)
            except OSError:
                pass
        try:
            logical = self.screen_size()
        except Refused:
            logical = image.size
        if logical and image.size != tuple(logical):
            image = image.resize(logical)
        return image

    # ---- input ----

    def settle(self):
        time.sleep(SETTLE)

    def move(self, x: int, y: int):
        self.remote.move(x, y)

    def click(self, x: int, y: int, button: int = 1, double: bool = False):
        self.remote.move(x, y)
        time.sleep(0.03)
        for _ in range(2 if double else 1):
            self.remote.button(button, True)
            self.remote.button(button, False)
            time.sleep(0.05)

    def scroll(self, x: int | None, y: int | None, direction: str, notches: int):
        if x is not None and y is not None:
            self.remote.move(x, y)
        vertical = direction in ("up", "down")
        sign = 1 if direction in ("down", "right") else -1
        for _ in range(notches):
            self.remote.axis(vertical, sign)
            time.sleep(0.01)

    @staticmethod
    def keysym(name: str) -> int:
        value = Gdk.keyval_from_name(name)
        if not value or value == 0xFFFFFF:
            raise ValueError(f"no keysym {name}")
        return value

    def chord(self, keysym_names: list[str]):
        codes = [self.keysym(name) for name in keysym_names]
        for code in codes:
            self.remote.key(code, True)
        for code in reversed(codes):
            self.remote.key(code, False)

    def _focused_field(self):
        """The field that has the keyboard in the active window, where it takes text through accessibility."""
        wid = self.active()
        if wid is None:
            return None
        for element in atspi.walk(self.frame(wid), 30):
            if atspi.has_state(element, "FOCUSED") and atspi.has_state(element, "EDITABLE"):
                return element
        return None

    def type_text(self, text: str) -> str:
        """
        Into the field with the keyboard: inserted at its caret through
        accessibility, which takes any letter - the virtual keyboard types only
        what the person's layout has keys for. Enter and Tab are pressed as keys,
        since they mean something to the window. Where no field takes text so,
        all of it as keys. Says which.
        """
        field = self._focused_field()
        if field is not None:
            for index, part in enumerate(text.replace("\t", "\n\t\n").split("\n")):
                if index and part != "\t":
                    self._key_tap(self.keysym("Return"))
                if part == "\t":
                    self._key_tap(self.keysym("Tab"))
                elif part and not atspi.insert_at_caret(field, part):
                    self._keys(part)
            return "inserted at the caret through accessibility"
        self._keys(text)
        return "typed as keys"

    def _key_tap(self, code: int):
        self.remote.key(code, True)
        self.remote.key(code, False)

    def _keys(self, text: str):
        """Letter by letter as keysyms; the desktop finds the key and the level, where the layout has one."""
        for char in text:
            code = {"\n": self.keysym("Return"), "\t": self.keysym("Tab")}.get(char) or Gdk.unicode_to_keyval(ord(char))
            self._key_tap(code)
            time.sleep(KEY_GAP)

    type_ascii = type_text
