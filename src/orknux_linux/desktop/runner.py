"""The desktop_* actions, with the arguments and answers Orknux for Windows has, so the server's one tool list serves both.

On X11, windows by their X11 id, input through XTest and pictures off the
screen (x11.py). On Wayland, windows by an id kept for each AT-SPI frame, and
input and pictures through the desktop's portals (wayland.py) - and since no
program learns where another's window is there, a control is clicked by its
own accessible action and a field is filled through its accessible text,
which is also what lets that work on a window behind another. What is in a
window is read through AT-SPI on both.
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

def program_of(pid: int | None) -> str | None:
    """The program a process runs, as Windows names a process: its command name."""
    if not pid:
        return None
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip() or None
    except OSError:
        return None


class Runner:
    def __init__(self, desk, wayland: bool = False):
        self.x = desk
        self.wayland = wayland
        # Whether an element's place on the screen can be trusted: not on Wayland, where a program knows only
        # where things are inside its own window.
        self.positions = getattr(desk, "positions", True)
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
        return handler(args)

    # ---- windows ----

    def _ids(self) -> list[int]:
        return self.x.client_list()

    def _title(self, wid: int) -> str:
        return self.x.title(wid)

    def _pid(self, wid: int) -> int | None:
        return self.x.pid(wid)

    def _window(self, args: dict, required: bool = False) -> int:
        given = number(args, "window")
        if given is None and required:
            raise Refused("Say which window: its id from desktop_windows.")
        wid = given if given is not None else (self.last if self.last is not None else self.x.active())
        if wid is None:
            raise Refused("Say which window: its id from desktop_windows.")
        if wid not in self._ids():
            raise Refused(f"There is no window {wid} any more. List the windows again with desktop_windows.")
        return wid

    def _described(self, wid: int) -> dict:
        return {"window": wid, "title": self._title(wid), "program": program_of(self._pid(wid))}

    def windows(self, args: dict) -> dict:
        active = self.x.active()
        listed = []
        for wid in self._ids():
            listed.append({
                "window": wid,
                "title": self._title(wid),
                "program": program_of(self._pid(wid)),
                "focused": wid == active,
                "minimized": self.x.minimized(wid),
                "last": wid == self.last,
            })
        answer = {"windows": listed}
        if self.wayland:
            answer["note"] = ("A Wayland desktop. Click controls by ref and type into fields by ref: that works on any "
                              "window, in front or not. x and y are points on a desktop_screenshot with screen set. "
                              "A program started before Orknux for Linux may publish nothing to read until it is "
                              "restarted.")
        return answer

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
        if self._bare(target) and not flag(args, "new"):
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
        own = getattr(self.x, "frame", None)
        frame = own(wid) if own is not None else atspi.frame_for(self._pid(wid), self._title(wid))
        if frame is None:
            raise Refused("This window publishes nothing to read: its program does not take part in accessibility "
                          "(AT-SPI), or was started before Orknux for Linux switched accessibility on and has to be "
                          "restarted. Take a desktop_screenshot of it instead.")
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
        if not self.positions:
            return None
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
            if not self.positions:
                return self._click_by_action(wid, element, reference, button, flag(args, "double"))
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

    def _click_by_action(self, wid: int, element, reference: str, button: int, double: bool) -> dict:
        """
        Wayland: the control's own accessible action - what a click on it does -
        since its place on the screen is not known here. Works on a window in
        front or behind; a right click is its menu action where it has one.
        """
        wanted = atspi.MENU_ACTIONS if button == 3 else atspi.CLICK_ACTIONS
        if button == 2:
            raise Refused(f"A middle click on {reference} cannot be made on Wayland, where a control's place on the screen "
                          "is not known. Click a point from a desktop_screenshot with screen set instead.")
        done = None
        for _ in range(2 if double else 1):
            done = atspi.do_action(element, wanted)
            if done is None:
                break
        if done is None:
            what = "a menu to open" if button == 3 else "an action to click"
            raise Refused(f"{reference} has {what} through accessibility, and on Wayland its place on the screen is not "
                          "known. Click a point from a desktop_screenshot with screen set instead.")
        self.last = wid
        self.x.settle()
        active = self.x.active()
        return {"clicked": reference, "at": None, "how": f"its accessible action \"{done}\"",
                "foreground": self._described(active) if active else {}}

    def _paste(self):
        self.x.chord(["Control_L", "v"])

    def type(self, args: dict) -> dict:
        typed = text(args, "text") or ""
        reference = text(args, "ref")
        append = flag(args, "append")
        if reference is not None and not self.positions:
            wid, element = self._element(args, reference)
            self.last = wid
            # The field's own text, set through accessibility: any letters, no window to bring forward, no clipboard.
            if atspi.set_text(element, typed, append):
                how = "set through accessibility"
                if flag(args, "submit"):
                    if atspi.do_action(element, ("activate",)) is None:
                        self._keys_to(wid, element, ["Return"])
                self.x.settle()
                return {"typed": reference, "how": how, "submitted": flag(args, "submit")}
            # A field that takes no text that way: the keyboard, with the field focused.
            self._keys_to(wid, element, None)
            if not append:
                self.x.chord(["Control_L", "a"])
                self.x.chord(["Delete"])
            how = self.x.type_text(typed)
            if flag(args, "submit"):
                self.x.chord(["Return"])
            self.x.settle()
            return {"typed": reference, "how": how, "submitted": flag(args, "submit")}
        if reference is not None:
            wid, element = self._element(args, reference)
            self._front(wid)
            if not atspi.grab_focus(element):
                point = self._point_of(element)
                if point is not None:
                    self.x.click(*point)
            time.sleep(0.05)
            if not append:
                self.x.chord(["Control_L", "a"])
                self.x.chord(["Delete"])
        elif number(args, "window") is not None:
            # Named a window and no element: that window in front first, as a key press does.
            self._front(self._window(args))
        how = "typed"
        if self.wayland:
            how = self.x.type_text(typed)
        elif clipboard.needed(typed):
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

    def _keys_to(self, wid: int, element, chord: list[str] | None):
        """Keys meant for one control on Wayland: its window must be the active one, or they would land elsewhere."""
        if not self._front(wid):
            raise Refused("That field takes no text through accessibility, and the desktop did not let its window come "
                          "to the front for the keyboard. Ask the person to click into the window, then try again.")
        atspi.grab_focus(element)
        time.sleep(0.05)
        if chord:
            self.x.chord(chord)

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
        if not self.positions:
            return self._scroll_wayland(args, reference, direction, amount)
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

    def _scroll_wayland(self, args: dict, reference: str | None, direction: str, amount: int) -> dict:
        """The scroll bar's value, through accessibility; failing that the wheel, where the window is the active one."""
        vertical = direction in ("up", "down")
        sign = 1 if direction in ("down", "right") else -1
        if reference is not None:
            wid, element = self._element(args, reference)
        else:
            wid = self._window(args)
            element = self._frame(wid)
        self.last = wid
        if atspi.scroll_by_value(element, vertical, sign * amount):
            self.x.settle()
            return {"scrolled": direction, "notches": amount, "how": "its scroll bar, through accessibility"}
        if not self._front(wid):
            raise Refused("Nothing here has a scroll bar to move through accessibility, and the desktop did not let the "
                          "window come to the front for the mouse wheel.")
        if reference is not None:
            atspi.grab_focus(element)
        self.x.scroll(None, None, direction, amount)
        self.x.settle()
        return {"scrolled": direction, "notches": amount, "how": "the mouse wheel, where the pointer is"}

    def screenshot(self, args: dict) -> dict:
        if flag(args, "screen"):
            width, height = self.x.screen_size()
            image, title, how = self.x.capture(0, 0, width, height), "The whole screen", "the whole screen"
        elif not self.positions:
            wid = self._window(args)
            came = self._front(wid)
            width, height = self.x.screen_size()
            image, title = self.x.capture(0, 0, width, height), self._title(wid)
            how = ("the whole screen: on Wayland no program is told where another's window is, so it cannot be cut "
                   "out" + ("" if came else "; the window did not come to the front, so it may be covered"))
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


def make_runner(display_name: str | None = None, settings=None) -> Runner:
    from .session import session_is_wayland

    if session_is_wayland():
        from .wayland import Wayland

        def save_token(token: str):
            if settings is not None:
                settings.portal_token = token
                settings.save()

        return Runner(Wayland(settings.portal_token if settings is not None else None, save_token), wayland=True)
    from . import x11

    return Runner(x11.X11(display_name))
