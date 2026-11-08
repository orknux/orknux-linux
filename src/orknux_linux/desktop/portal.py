"""The XDG desktop portals: how a program acts on a Wayland desktop it does not own.

Wayland gives no program another's input or pixels. What it gives instead are
portals, served by the desktop itself (xdg-desktop-portal-gnome, -kde), which
ask the person once and then act for the program: RemoteDesktop for a virtual
keyboard and pointer, ScreenCast to say where the monitors are so the pointer
can be placed absolutely, Screenshot for pictures, GlobalShortcuts for
Ctrl+Alt+Q. RemoteDesktop's answer is remembered with a restore token, so the
question is asked on the first connection and not on every start.

Every portal call that needs an answer is a Request: the method returns at
once, and the answer arrives later as a Response signal on a path made from
this connection's name and a token chosen here. Each such call runs its own
GLib main context until that signal comes, so it works from any thread, with
or without a GTK main loop running.
"""

import itertools
import os
import threading
import time
from urllib.parse import unquote, urlparse

import gi

from gi.repository import Gio, GLib  # noqa: E402

from ..core.errors import Refused  # noqa: E402

BUS = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
REMOTE = "org.freedesktop.portal.RemoteDesktop"
SCREENCAST = "org.freedesktop.portal.ScreenCast"
SCREENSHOT = "org.freedesktop.portal.Screenshot"
SHORTCUTS = "org.freedesktop.portal.GlobalShortcuts"

# evdev codes, which is what NotifyPointerButton takes.
BUTTONS = {1: 0x110, 2: 0x112, 3: 0x111}

# How long a person is given to answer the desktop's question.
ASKING_SECONDS = 180

_tokens = itertools.count(1)


def s(value):
    return GLib.Variant("s", value)


def u(value):
    return GLib.Variant("u", value)


def b(value):
    return GLib.Variant("b", value)


APP_ID = "ai.orknux.Linux"

# What a portal that is there but does not offer the interface answers, as opposed to one that is busy.
ABSENT = ("org.freedesktop.DBus.Error.InvalidArgs", "org.freedesktop.DBus.Error.UnknownInterface",
          "org.freedesktop.DBus.Error.UnknownMethod", "org.freedesktop.DBus.Error.ServiceUnknown",
          "org.freedesktop.DBus.Error.NameHasNoOwner")


def install_desktop_entry():
    """
    The app id's .desktop file, which is how the desktop names this program in
    its questions ("Orknux for Linux wants to...") and what lets the portals
    take the id at all. Written once, into the person's own applications.
    """
    import sys
    from pathlib import Path

    folder = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"
    path = folder / f"{APP_ID}.desktop"
    if path.exists():
        return
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join([
            "[Desktop Entry]", "Type=Application", "Name=Orknux for Linux",
            "Comment=Lend this desktop to your Orknux agents",
            f"Exec={sys.executable} -m orknux_linux.cli", "Icon=computer", "Terminal=false",
            "Categories=Utility;", "",
        ]))
    except OSError:
        pass


class Portal:
    def __init__(self, bus=None):
        self.bus = bus or Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.sender = self.bus.get_unique_name()[1:].replace(".", "_")
        self._versions: dict[str, int] = {}
        self._register()

    def _register(self):
        """
        Says which app this is, before any other portal call on the connection:
        a program not in a sandbox has no app id the portals can see, and
        GlobalShortcuts, among others, refuses one without.
        """
        install_desktop_entry()
        try:
            self.bus.call_sync(BUS, PATH, "org.freedesktop.host.portal.Registry", "Register",
                               GLib.Variant("(sa{sv})", (APP_ID, {})), None, Gio.DBusCallFlags.NONE, 5000, None)
        except GLib.Error:
            pass  # an older portal without the registry; the rest works without an id

    def version(self, interface: str) -> int:
        """The interface's version, 0 where the desktop does not offer it; a portal that does not answer is said."""
        if interface in self._versions:
            return self._versions[interface]
        try:
            reply = self.bus.call_sync(BUS, PATH, "org.freedesktop.DBus.Properties", "Get",
                                       GLib.Variant("(ss)", (interface, "version")), None,
                                       Gio.DBusCallFlags.NONE, 5000, None)
            found = int(reply.unpack()[0])
        except GLib.Error as failed:
            if Gio.DBusError.get_remote_error(failed) not in ABSENT:
                raise Refused("The desktop's portal is not answering. It may be waiting for a question it asked on "
                              "the screen - \"Allow Remote Interaction\", \"Allow Apps to Take Screenshots?\" - to be "
                              "answered by the person.") from None
            found = 0
        self._versions[interface] = found
        return found

    def request(self, interface: str, method: str, signature: str, args: tuple, options: dict,
                timeout: float = ASKING_SECONDS) -> dict:
        """Calls a portal method that answers through a Request, and waits for the answer's results."""
        token = f"orknux{os.getpid()}x{next(_tokens)}"
        options = {**options, "handle_token": s(token)}
        path = f"/org/freedesktop/portal/desktop/request/{self.sender}/{token}"
        answer: dict = {}
        context = GLib.MainContext.new()
        context.push_thread_default()
        try:
            def responded(_connection, _sender, _path, _interface, _signal, parameters):
                code, results = parameters.unpack()
                answer["code"], answer["results"] = code, results

            subscription = self.bus.signal_subscribe(BUS, "org.freedesktop.portal.Request", "Response", path,
                                                     None, Gio.DBusSignalFlags.NONE, responded)
            try:
                self.bus.call_sync(BUS, PATH, interface, method,
                                   GLib.Variant(f"({signature}a{{sv}})", (*args, options)), None,
                                   Gio.DBusCallFlags.NONE, 30_000, None)
                until = time.monotonic() + timeout
                while "code" not in answer and time.monotonic() < until:
                    if not context.iteration(False):
                        time.sleep(0.01)
            finally:
                self.bus.signal_unsubscribe(subscription)
        except GLib.Error as failed:
            raise Refused(f"The desktop's portal refused {method}: {failed.message}") from None
        finally:
            context.pop_thread_default()
        if "code" not in answer:
            raise Refused(f"The desktop did not answer {method} within {int(timeout)} seconds.")
        if answer["code"] == 1:
            raise Refused(f"The person declined the desktop's question for {method}.")
        if answer["code"] != 0:
            raise Refused(f"The desktop could not do {method}.")
        return answer["results"]

    def call(self, interface: str, method: str, signature: str, args: tuple):
        self.bus.call_sync(BUS, PATH, interface, method, GLib.Variant(f"({signature})", args), None,
                           Gio.DBusCallFlags.NONE, 5000, None)


class RemoteControl:
    """
    A RemoteDesktop session with a keyboard and a pointer, and a ScreenCast of
    every monitor so the pointer can be put at a point rather than moved by a
    distance. Made on first use, which is when the desktop asks the person; the
    restore token it hands back is kept through [save_token] so it is not
    asked again. GNOME shows its own remote-control icon in the top bar while
    the session lives.
    """

    def __init__(self, portal: Portal, token: str | None = None, save_token=lambda token: None):
        self.portal = portal
        self.token = token
        self.save_token = save_token
        self.session: str | None = None
        self.devices = 0
        self.streams: list[tuple[int, int, int, int, int]] = []  # node, x, y, width, height - logical pixels
        self._lock = threading.RLock()

    def available(self) -> bool:
        return self.portal.version(REMOTE) >= 1

    def ensure(self):
        with self._lock:
            if self.session is not None:
                return
            if not self.available():
                raise Refused("This desktop has no RemoteDesktop portal, so nothing can be clicked or typed on it "
                              "here. Install xdg-desktop-portal-gnome or xdg-desktop-portal-kde.")
            made = self.portal.request(REMOTE, "CreateSession", "", (), {"session_handle_token": s(f"orknux{next(_tokens)}")})
            session = made["session_handle"]
            devices = {"types": u(3)}  # keyboard and pointer
            if self.portal.version(REMOTE) >= 2:
                devices["persist_mode"] = u(2)  # until the person revokes it
                if self.token:
                    devices["restore_token"] = s(self.token)
            self.portal.request(REMOTE, "SelectDevices", "o", (session,), devices)
            self.portal.request(SCREENCAST, "SelectSources", "o", (session,), {"types": u(1), "multiple": b(True)})
            started = self.portal.request(REMOTE, "Start", "os", (session, ""), {})
            granted = int(started.get("devices", 0))
            if not granted & 3:
                try:
                    self.portal.bus.call_sync(BUS, session, "org.freedesktop.portal.Session", "Close", None, None,
                                              Gio.DBusCallFlags.NONE, 2000, None)
                except GLib.Error:
                    pass
                raise Refused("The person shared the screen but did not allow remote interaction, so nothing can be "
                              "clicked or typed. Ask them to switch on \"Allow Remote Interaction\" when the desktop "
                              "asks again.")
            self.devices = granted
            self.streams = []
            for node, properties in started.get("streams", []):
                x, y = properties.get("position", (0, 0))
                width, height = properties.get("size", (0, 0))
                self.streams.append((int(node), int(x), int(y), int(width), int(height)))
            fresh = started.get("restore_token")
            if fresh and fresh != self.token:
                self.token = fresh
                self.save_token(fresh)
            self.session = session

    def close(self):
        with self._lock:
            if self.session is None:
                return
            try:
                self.portal.bus.call_sync(BUS, self.session, "org.freedesktop.portal.Session", "Close", None, None,
                                          Gio.DBusCallFlags.NONE, 2000, None)
            except GLib.Error:
                pass
            self.session = None

    def _notify(self, method: str, signature: str, *args):
        """One input event; a session the person stopped from the top bar is made again, once."""
        for attempt in (0, 1):
            self.ensure()
            try:
                self.portal.call(REMOTE, method, f"oa{{sv}}{signature}", (self.session, {}, *args))
                return
            except GLib.Error as failed:
                self.session = None
                if attempt:
                    raise Refused(f"The desktop refused the input: {failed.message}") from None

    def bounds(self) -> tuple[int, int, int, int] | None:
        """Every monitor together, in logical pixels: x, y, width, height."""
        self.ensure()
        if not self.streams:
            return None
        left = min(x for _, x, _, _, _ in self.streams)
        top = min(y for _, _, y, _, _ in self.streams)
        right = max(x + w for _, x, _, w, _ in self.streams)
        bottom = max(y + h for _, _, y, _, h in self.streams)
        return left, top, right - left, bottom - top

    def stream_at(self, x: float, y: float) -> tuple[int, float, float]:
        self.ensure()
        for node, sx, sy, width, height in self.streams:
            if sx <= x < sx + width and sy <= y < sy + height:
                return node, x - sx, y - sy
        raise Refused(f"{int(x)},{int(y)} is on no monitor. Take a desktop_screenshot with screen set for the coordinates.")

    def picture(self):
        """
        The whole desktop as a Pillow image in logical pixels, from this
        session's own screen casts: one frame of each monitor, placed where the
        monitor is. The person allowed this when they allowed the session, so
        it asks nothing more - and works with no window of this program in
        front, which GNOME's Screenshot portal requires to ask its own question.
        None where GStreamer's PipeWire source is not installed.
        """
        try:
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
        except (ImportError, ValueError):
            return None
        Gst.init(None)
        if Gst.ElementFactory.find("pipewiresrc") is None:
            return None
        from PIL import Image

        self.ensure()
        left, top, width, height = self.bounds()
        canvas = Image.new("RGB", (width, height))
        for node, x, y, w, h in self.streams:
            reply, fds = self.portal.bus.call_with_unix_fd_list_sync(
                BUS, PATH, SCREENCAST, "OpenPipeWireRemote", GLib.Variant("(oa{sv})", (self.session, {})),
                GLib.VariantType("(h)"), Gio.DBusCallFlags.NONE, 5000, None, None)
            fd = fds.get(reply.unpack()[0])
            pipeline = Gst.parse_launch(
                f"pipewiresrc fd={fd} path={node} always-copy=true ! videoconvert ! "
                "video/x-raw,format=RGBx ! appsink name=sink max-buffers=1 drop=true")
            try:
                pipeline.set_state(Gst.State.PLAYING)
                sample = pipeline.get_by_name("sink").emit("try-pull-sample", 5 * Gst.SECOND)
                if sample is None:
                    raise Refused("The screen cast sent no picture within five seconds.")
                structure = sample.get_caps().get_structure(0)
                fw, fh = structure.get_value("width"), structure.get_value("height")
                buffer = sample.get_buffer()
                found, mapped = buffer.map(Gst.MapFlags.READ)
                try:
                    stride = len(mapped.data) // fh
                    image = Image.frombuffer("RGB", (fw, fh), bytes(mapped.data), "raw", "RGBX", stride, 1)
                finally:
                    buffer.unmap(mapped)
            finally:
                pipeline.set_state(Gst.State.NULL)
                try:
                    os.close(fd)
                except OSError:
                    pass
            if (fw, fh) != (w, h):
                image = image.resize((w, h))
            canvas.paste(image, (x - left, y - top))
        return canvas

    def move(self, x: float, y: float):
        node, local_x, local_y = self.stream_at(x, y)
        self._notify("NotifyPointerMotionAbsolute", "udd", node, float(local_x), float(local_y))

    def button(self, button: int, pressed: bool):
        self._notify("NotifyPointerButton", "iu", BUTTONS[button], 1 if pressed else 0)

    def axis(self, vertical: bool, steps: int):
        self._notify("NotifyPointerAxisDiscrete", "ui", 0 if vertical else 1, steps)

    def key(self, keysym: int, pressed: bool):
        self._notify("NotifyKeyboardKeysym", "iu", keysym, 1 if pressed else 0)


def screenshot_file(portal: Portal) -> str:
    """The whole screen, through the Screenshot portal, as the path of the file the desktop wrote."""
    if portal.version(SCREENSHOT) < 1:
        raise Refused("This desktop has no Screenshot portal, so no picture can be taken here.")
    results = portal.request(SCREENSHOT, "Screenshot", "s", ("",), {"interactive": b(False)})
    uri = results.get("uri")
    if not uri:
        raise Refused("The desktop took no screenshot.")
    return unquote(urlparse(uri).path)


class StopShortcut:
    """
    Ctrl+Alt+Q through the GlobalShortcuts portal, the Wayland way to hear a key
    pressed in somebody else's window. The desktop asks the person to confirm
    the shortcut once. Listens on a thread of its own.
    """

    def __init__(self, on_press, portal: Portal | None = None):
        self.on_press = on_press
        self.portal = portal or Portal()
        if self.portal.version(SHORTCUTS) < 1:
            raise Refused("this desktop has no GlobalShortcuts portal")
        self.ready = threading.Event()
        self.failed: str | None = None
        threading.Thread(target=self._run, daemon=True, name="stop-shortcut").start()

    def _run(self):
        context = GLib.MainContext.new()
        context.push_thread_default()
        try:
            made = self.portal.request(SHORTCUTS, "CreateSession", "", (), {"session_handle_token": s(f"orknux{next(_tokens)}")})
            session = made["session_handle"]

            def activated(_c, _s, _p, _i, _signal, parameters):
                if parameters.unpack()[1] == "stop":
                    self.on_press()

            self.portal.bus.signal_subscribe(BUS, SHORTCUTS, "Activated", PATH, None, Gio.DBusSignalFlags.NONE, activated)
            shortcut = ("stop", {"description": s("Stop the Orknux agent using this computer"),
                                 "preferred_trigger": s("CTRL+ALT+q")})
            self.portal.request(SHORTCUTS, "BindShortcuts", "oa(sa{sv})s", (session, [shortcut], ""), {})
        except Exception as failed:  # noqa: BLE001 - said, not raised: the client works without the shortcut
            self.failed = str(failed)
            self.ready.set()
            context.pop_thread_default()
            return
        self.ready.set()
        loop = GLib.MainLoop.new(context, False)
        loop.run()
