"""The desktop_* actions, with the arguments and answers Orknux for Windows has, so the server's one tool list serves both.

Windows by X11 id, the same number an agent reads off desktop_windows and hands
back; what is in them through AT-SPI. On Wayland the windows and what is in them
can still be read, through AT-SPI, but nothing is clicked, typed or
photographed: X11 input reaches only XWayland windows there, and an agent that
can act on some windows and not others cannot be told which. Said, not tried.
"""

import base64
import io
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from ..core import appnames, keychord
from ..core.args import flag, number, text
from ..core.connection import wait_for
from ..core.errors import Refused
from ..core.snapshot import RefTable, lines_of, render
from . import apps, atspi, clipboard

WAYLAND = ("Orknux for Linux cannot click, type, press keys, take screenshots or move windows in a Wayland "
           "session yet. Log out and choose the X11 session - on GNOME, \"GNOME on Xorg\" from the gear at "
           "sign-in - then connect again. Listing windows and reading them with desktop_snapshot works.")


def program_of(pid: int | None) -> str | None:
    """The program a process runs, as Windows names a process: its command name."""
    if not pid:
        return None
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip() or None
    except OSError:
        return None


class Runner:
    def __init__(self, x11=None, wayland: bool = False):
        self.x = x11
        self.wayland = wayland
        self.refs: dict[int, RefTable] = {}
        self.last: int | None = None
        atspi.init()

    def run(self, action: str, args: dict) -> dict:
        handlers = {
            "windows": self.windows, "open": self.open, "focus": self.focus, "snapshot": self.snapshot,
            "click": self.click, "type": self.type, "press": self.press, "scroll": self.scroll,
            "screenshot": self.screenshot, "close": self.close,
        }
        handler = handlers.get(action)
        if handler is None:
            raise Refused(f'Orknux for Linux does not know the action "{action}". It may be older than the server.')
        if self.wayland and action not in ("windows", "snapshot", "open"):
            raise Refused(WAYLAND)
        return handler(args)

    # ---- windows ----

    def _ids(self) -> list[int]:
        if self.wayland:
            return [self._wayland_id(pid, frame) for pid, frame in atspi.frames()]
        return self.x.client_list()

    @staticmethod
    def _wayland_id(pid, frame) -> int:
        return abs(hash((pid, atspi.name_of(frame)))) % (2 ** 31)

    def _title(self, wid: int) -> str:
        if self.wayland:
            for pid, frame in atspi.frames():
                if self._wayland_id(pid, frame) == wid:
                    return atspi.name_of(frame)
            return ""
        return self.x.title(wid)

    def _pid(self, wid: int) -> int | None:
        if self.wayland:
            for pid, frame in atspi.frames():
                if self._wayland_id(pid, frame) == wid:
                    return pid
            return None
        return self.x.pid(wid)

    def _window(self, args: dict, required: bool = False) -> int:
        given = number(args, "window")
        if given is None and required:
            raise Refused("Say which window: its id from desktop_windows.")
        wid = given if given is not None else (self.last if self.last is not None else (None if self.wayland else self.x.active()))
        if wid is None:
            raise Refused("Say which window: its id from desktop_windows.")
        if wid not in self._ids():
            raise Refused(f"There is no window {wid} any more. List the windows again with desktop_windows.")
        return wid

    def _described(self, wid: int) -> dict:
        return {"window": wid, "title": self._title(wid), "program": program_of(self._pid(wid))}

    def windows(self, args: dict) -> dict:
        active = None if self.wayland else self.x.active()
        listed = []
        for wid in self._ids():
            listed.append({
                "window": wid,
                "title": self._title(wid),
                "program": program_of(self._pid(wid)),
                "focused": wid == active,
                "minimized": False if self.wayland else self.x.minimized(wid),
                "last": wid == self.last,
            })
        return {"windows": listed}

    def _front(self, wid: int) -> bool:
        came = self.x.front(wid)
        self.last = wid
        return came

    def focus(self, args: dict) -> dict:
        wid = self._window(args, required=True)
        came = self._front(wid)
        said = self._described(wid)
        # Whether the window manager let it come forward: an agent told plainly that it did not stops asking for
        # pictures of a window that is behind another.
        said["inFront"] = came
        return said

    # ---- open ----

    @staticmethod
    def _bare(target: str) -> bool:
        return not any(mark in target for mark in ("/", "\\", ":"))

    def open(self, args: dict) -> dict:
        target = text(args, "target")
        if target is None:
            raise Refused("Say what to open: a program, a file, a folder or an address.")
        extra = shlex.split(text(args, "arguments") or "")
        # An app already running is brought forward rather than started again; only by the program's own name.
        if self._bare(target) and not flag(args, "new") and not self.wayland:
            for wid in self._ids():
                if appnames.is_program(target, program_of(self.x.pid(wid))):
                    came = self._front(wid)
                    said = self._described(wid)
                    said["alreadyRunning"] = True
                    said["inFront"] = came
                    return said
        before = set(self._ids())
        started = None
        from_menu = None
        try:
            if self._bare(target) and shutil.which(target):
                started = subprocess.Popen([target, *extra], start_new_session=True,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif self._bare(target):
                found, near = apps.find(target)
                if found is None:
                    said = f'Linux could not open "{target}": it is not a program on the PATH, and no app in the menu is called that either.'
                    if near:
                        said += " Close names there: " + ", ".join(near) + "."
                    raise Refused(said)
                from_menu = found[0]
                started = apps.launch(found[1], extra)
            else:
                opener = shutil.which("xdg-open") or shutil.which("gio")
                if opener is None:
                    raise Refused(f'Linux could not open "{target}": there is no xdg-open to hand it to.')
                command = [opener, target] if opener.endswith("xdg-open") else [opener, "open", target]
                started = subprocess.Popen(command, start_new_session=True,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as failed:
            raise Refused(f'Linux could not open "{target}": {failed}') from None
        if self.wayland:
            return {"opened": target, "note": "Started. On Wayland its window can be read with desktop_snapshot once it appears in desktop_windows."}
        # A new window, or failing that the one that came to the front: many programs hand off to a running copy.
        opened = None
        until = time.monotonic() + 15
        while time.monotonic() < until and opened is None:
            time.sleep(0.25)
            fresh = [wid for wid in self._ids() if wid not in before]
            if fresh:
                mine = [wid for wid in fresh if started is not None and self.x.pid(wid) == started.pid]
                opened = (mine or fresh)[0]
        front = self.x.active()
        if front is not None and front not in before:
            opened = front
        if opened is None:
            opened = front
        if opened is None:
            return {"opened": target, "note": "It started, but no window appeared yet. List the windows to find it."}
        self.last = opened
        said = self._described(opened)
        if from_menu is not None:
            said["fromApplications"] = from_menu
        said["inFront"] = self.x.active() == opened
        return said

    # ---- reading ----

    def _frame(self, wid: int):
        frame = atspi.frame_for(self._pid(wid), self._title(wid))
        if frame is None:
            raise Refused("This window publishes nothing to read: its program does not take part in accessibility "
                          "(AT-SPI). Take a desktop_screenshot of it instead.")
        return frame

    def snapshot(self, args: dict) -> dict:
        wid = self._window(args)
        table = RefTable()
        root, count = atspi.tree(self._frame(wid), table)
        self.refs[wid] = table
        self.last = wid
        lines = lines_of(root, flag(args, "interactiveOnly"))
        answer = render(wid, self._title(wid), lines, text(args, "find"), number(args, "maxCharacters") or 20_000)
        if count >= atspi.MOST_NODES:
            answer["note"] = f"The window has more than {atspi.MOST_NODES} elements; only the first were read. Use find, or focus on one part."
        return answer

    def _element(self, args: dict, reference: str):
        wid = self._window(args)
        table = self.refs.get(wid)
        if table is None:
            raise Refused("Take a desktop_snapshot of this window first; refs come from it.")
        return wid, table.resolve(reference)

    def _point_of(self, element) -> tuple[int, int] | None:
        box = atspi.extents(element)
        if box is None:
            return None
        x, y, w, h = box
        return x + w // 2, y + h // 2

    # ---- acting ----

    def click(self, args: dict) -> dict:
        button = {"left": 1, "middle": 2, "right": 3}.get((text(args, "button") or "left").lower())
        if button is None:
            raise Refused(f'"{text(args, "button")}" is not a mouse button. Use left, right or middle.')
        reference = text(args, "ref")
        if reference is not None:
            wid, element = self._element(args, reference)
            self._front(wid)
            point = self._point_of(element)
            if point is None:
                # Nowhere on the screen to press: its own action, which is what a click on it would have done.
                if button == 1 and atspi.activate(element):
                    self.x.settle()
                    return {"clicked": reference, "at": None, "foreground": self._described(self.x.active()) if self.x.active() else {}}
                raise Refused(f"{reference} is not on the screen. Scroll it into view, then take a fresh snapshot.")
            clicked = reference
        else:
            x, y = number(args, "x"), number(args, "y")
            if x is None or y is None:
                raise Refused("Give the control's ref from desktop_snapshot, or x and y in screen pixels.")
            point, clicked = (x, y), f"{x},{y}"
        self.x.click(point[0], point[1], button, flag(args, "double"))
        self.x.settle()
        active = self.x.active()
        return {"clicked": clicked, "at": [point[0], point[1]], "foreground": self._described(active) if active else {}}

    def _paste(self):
        self.x.chord(["Control_L", "v"])

    def type(self, args: dict) -> dict:
        typed = text(args, "text") or ""
        reference = text(args, "ref")
        if reference is not None:
            wid, element = self._element(args, reference)
            self._front(wid)
            if not atspi.grab_focus(element):
                point = self._point_of(element)
                if point is not None:
                    self.x.click(*point)
            time.sleep(0.05)
            if not flag(args, "append"):
                self.x.chord(["Control_L", "a"])
                self.x.chord(["Delete"])
        elif number(args, "window") is not None:
            # Named a window and no element: that window in front first, as a key press does.
            self._front(self._window(args))
        how = "typed"
        if clipboard.needed(typed):
            if not clipboard.available():
                raise Refused("This text has letters past ASCII, which are pasted rather than typed, and xclip is not "
                              "installed. Install xclip (sudo apt install xclip) and try again.")
            clipboard.paste(typed, self._paste)
            how = "pasted, the clipboard's text given back after"
        elif typed:
            self.x.type_ascii(typed)
        if flag(args, "submit"):
            self.x.chord(["Return"])
        self.x.settle()
        return {"typed": reference or "where the focus was", "how": how, "submitted": flag(args, "submit")}

    def press(self, args: dict) -> dict:
        chord = keychord.parse(text(args, "keys"))
        if number(args, "window") is not None:
            self._front(self._window(args))
        try:
            self.x.chord(chord.keysyms())
        except ValueError as missing:
            raise Refused(f"{chord} cannot be pressed on this keyboard: {missing}.") from None
        self.x.settle()
        return {"pressed": str(chord)}

    def scroll(self, args: dict) -> dict:
        amount = max(1, min(50, number(args, "amount") or 5))
        direction = (text(args, "direction") or "down").lower()
        if direction not in ("down", "up", "left", "right"):
            raise Refused(f'"{direction}" is not a direction. Use down, up, left or right.')
        reference = text(args, "ref")
        if reference is not None:
            wid, element = self._element(args, reference)
            self._front(wid)
            point = self._point_of(element)
        else:
            wid = self._window(args)
            self._front(wid)
            x, y, w, h = self.x.geometry(wid)
            point = (x + w // 2, y + h // 2)
        if point is None:
            raise Refused(f"{reference} is not on the screen to scroll.")
        self.x.scroll(point[0], point[1], direction, amount)
        self.x.settle()
        return {"scrolled": direction, "notches": amount}

    def screenshot(self, args: dict) -> dict:
        if flag(args, "screen"):
            width, height = self.x.screen_size()
            image, title, how = self.x.capture(0, 0, width, height), "The whole screen", "the whole screen"
        else:
            wid = self._window(args)
            came = self._front(wid)
            image = self.x.capture(*self.x.geometry(wid))
            title = self._title(wid)
            # X11 has no PrintWindow: without a compositor a covered window cannot paint itself into a picture,
            # so it is brought forward and the screen where it sits is copied - and the answer says which happened.
            how = "copied from the screen where the window is" + ("" if came else "; it did not come to the front, so something may cover it")
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=80)
        return {"data": base64.b64encode(buffer.getvalue()).decode(), "mimeType": "image/jpeg", "title": title,
                "width": image.width, "height": image.height, "how": how}

    def close(self, args: dict) -> dict:
        wid = self._window(args, required=True)
        self.x.close(wid)
        self.refs.pop(wid, None)
        if self.last == wid:
            self.last = None
        gone = wait_for(lambda: not self.x.exists(wid), 3)
        self.x.settle()
        return {"closed": wid, "stillOpen": not gone}


def make_runner(display_name: str | None = None) -> Runner:
    from . import x11

    if x11.session_is_wayland() and not os.environ.get("DISPLAY"):
        return Runner(None, wayland=True)
    if x11.session_is_wayland():
        return Runner(x11.X11(display_name), wayland=True)
    return Runner(x11.X11(display_name))
