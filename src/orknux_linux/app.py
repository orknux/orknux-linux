"""The window a person connects from, and the strip that says an agent is at work.

GTK 3 rather than 4: GTK 4 cannot place a window, and the notice strip has to
stand at the top of the screen over everything, which is what GTK 3's
keep-above and move are for. The connection runs on a thread of its own; every
change to the window goes back through GLib.idle_add.
"""

import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import VERSION  # noqa: E402
from .cli import connect  # noqa: E402
from .core.errors import ConnectionRefused  # noqa: E402
from .settings import Settings  # noqa: E402

HELP = ("Paste the pairing link from Orknux - Preferences › Connected clients › Connect a client - and press Connect. "
        "An access token with the server address works too. Your agents act on this computer as you while it is "
        "connected. Ctrl+Alt+Q stops them at any time.")


class Notice(Gtk.Window):
    """A strip along the top of the screen while an agent is acting, so nobody is surprised by their own mouse."""

    def __init__(self):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        label = Gtk.Label(label="An Orknux agent is using this computer - Ctrl+Alt+Q stops it")
        label.set_margin_top(6)
        label.set_margin_bottom(6)
        label.set_margin_start(16)
        label.set_margin_end(16)
        self.add(label)
        css = Gtk.CssProvider()
        css.load_from_data(b"window { background: #4a66c4; color: white; font-weight: bold; }")
        self.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        label.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._hide_at = 0.0

    def acting(self):
        self.show_all()
        screen = Gdk.Screen.get_default()
        width = self.get_preferred_width()[1]
        self.move(max(0, (screen.get_width() - width) // 2), 0)
        self._hide_at = 0.0

    def done(self):
        # A moment after the last action rather than at once, so a run of actions does not flicker the strip.
        self._hide_at = time.monotonic() + 1.5
        GLib.timeout_add(1600, self._maybe_hide)

    def _maybe_hide(self):
        if self._hide_at and time.monotonic() >= self._hide_at:
            self.hide()
        return False


def _wayland() -> bool:
    from .desktop.session import session_is_wayland

    return session_is_wayland()


class Notification:
    """
    The strip's place on Wayland, where a window cannot put itself at the top
    of the screen: one desktop notification while an agent acts, withdrawn a
    moment after it stops. GNOME also shows its own remote-control icon in the
    top bar for as long as the agent holds the keyboard and pointer.
    """

    def __init__(self):
        from gi.repository import Gio

        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.shown = 0
        self._hide_at = 0.0

    def acting(self):
        from gi.repository import Gio

        self._hide_at = 0.0
        if self.shown:
            return
        try:
            reply = self.bus.call_sync(
                "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                "Notify", GLib.Variant("(susssasa{sv}i)", (
                    "Orknux for Linux", 0, "", "An Orknux agent is using this computer",
                    "Ctrl+Alt+Q stops it at once.", [], {"urgency": GLib.Variant("y", 1)}, 0)),
                None, Gio.DBusCallFlags.NONE, 2000, None)
            self.shown = reply.unpack()[0]
        except Exception:
            self.shown = 0

    def done(self):
        self._hide_at = time.monotonic() + 1.5
        GLib.timeout_add(1600, self._maybe_hide)

    def _maybe_hide(self):
        if self._hide_at and time.monotonic() >= self._hide_at:
            self.hide()
        return False

    def hide(self):
        from gi.repository import Gio

        if not self.shown:
            return
        try:
            self.bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                               "org.freedesktop.Notifications", "CloseNotification", GLib.Variant("(u)", (self.shown,)),
                               None, Gio.DBusCallFlags.NONE, 2000, None)
        except Exception:
            pass
        self.shown = 0


class MainWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title=f"Orknux for Linux {VERSION}")
        self.set_default_size(460, 560)
        self.settings = Settings.load()
        self.connection = None
        self.notice = Notice() if not _wayland() else Notification()

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        self.add(box)

        box.pack_start(Gtk.Label(label="Pairing link or server", xalign=0), False, False, 0)
        self.server = Gtk.Entry(text=self.settings.server, placeholder_text="https://orknux.example.com/pair/K7P-4QX")
        box.pack_start(self.server, False, False, 0)
        box.pack_start(Gtk.Label(label="Access token, if not a pairing link", xalign=0), False, False, 0)
        self.token = Gtk.Entry(visibility=False, text=self.settings.token, placeholder_text="orkx_…")
        # An eye at the end of the box shows what was pasted and hides it again: a token is checked by reading it.
        self.token.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "view-reveal-symbolic")
        self.token.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, "Show the token")
        self.token.connect("icon-press", lambda *_: self._toggle_token())
        box.pack_start(self.token, False, False, 0)
        help_label = Gtk.Label(label=HELP, xalign=0, wrap=True)
        help_label.get_style_context().add_class("dim-label")
        box.pack_start(help_label, False, False, 6)

        row = Gtk.Box(spacing=12)
        self.connect_button = Gtk.Button(label="Connect")
        self.connect_button.connect("clicked", lambda *_: self.start())
        self.disconnect_button = Gtk.Button(label="Disconnect")
        self.disconnect_button.connect("clicked", lambda *_: self.stop("Disconnected.", by_person=True))
        self.state = Gtk.Label(label="Not connected", xalign=0)
        row.pack_start(self.connect_button, False, False, 0)
        row.pack_start(self.disconnect_button, False, False, 0)
        row.pack_start(self.state, False, False, 0)
        box.pack_start(row, False, False, 6)
        self.message = Gtk.Label(xalign=0, wrap=True)
        box.pack_start(self.message, False, False, 0)

        box.pack_start(Gtk.Label(label="WHAT YOUR AGENTS DID", xalign=0), False, False, 6)
        self.log_store = Gtk.ListStore(str)
        log_view = Gtk.TreeView(model=self.log_store, headers_visible=False)
        log_view.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(log_view)
        box.pack_start(scrolled, True, True, 0)

        self.connect("destroy", lambda *_: self.quit())
        self.show_all()
        self.disconnect_button.hide()
        from .cli import accessibility_on, claim_stop_key
        from .desktop.session import SSH_WARNING, forwarded_over_ssh

        if forwarded_over_ssh():
            self.say(SSH_WARNING)

        accessibility_on()
        claim = threading.Thread(target=lambda: self._claimed(claim_stop_key(
            lambda: GLib.idle_add(self.stop, "Stopped with Ctrl+Alt+Q.", True))), daemon=True)
        claim.start()
        # An Orknux on this computer is found and its address filled in, where nothing is there yet.
        if not self.server.get_text().strip():
            def look():
                from .core.pairing import find_local

                found = find_local()
                if found:
                    GLib.idle_add(lambda: (self.server.get_text().strip() or self.server.set_text(found), False)[1])

            threading.Thread(target=look, daemon=True).start()
        # Connected when it last ran, and not disconnected since: connect again by itself, as it was.
        if self.settings.reconnect and self.settings.server and self.settings.token:
            GLib.idle_add(self.start)

    def _toggle_token(self):
        shown = not self.token.get_visibility()
        self.token.set_visibility(shown)
        self.token.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "view-conceal-symbolic" if shown else "view-reveal-symbolic")
        self.token.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, "Hide the token" if shown else "Show the token")

    def _claimed(self, said: str | None):
        if said:
            GLib.idle_add(lambda: (self.say(f"Ctrl+Alt+Q could not be claimed: {said}"), False)[1])

    # ---- the log and the state ----

    def log(self, line: str, failed: bool):
        GLib.idle_add(lambda: (self.log_store.prepend([time.strftime("%H:%M:%S") + "  " + ("! " if failed else "") + line]), False)[1])

    def set_state(self, said: str):
        GLib.idle_add(lambda: (self.state.set_text(said), False)[1])

    def say(self, text: str):
        self.message.set_text(text)

    def busy(self, on: bool):
        GLib.idle_add(lambda: (self.notice.acting() if on else self.notice.done(), False)[1])

    def showing(self, connected: bool):
        self.connect_button.set_visible(not connected)
        self.disconnect_button.set_visible(connected)
        self.server.set_sensitive(not connected)
        self.token.set_sensitive(not connected)

    # ---- connecting ----

    def start(self):
        self.say("")
        self.state.set_text("Connecting…")
        self.connect_button.set_sensitive(False)
        server, secret = self.server.get_text(), self.token.get_text()

        def work():
            try:
                connection, user = connect(server, secret, self.settings, log=lambda line: None)
            except ConnectionRefused as refused:
                GLib.idle_add(self._refused, str(refused))
                return
            except Exception as failed:  # noqa: BLE001
                # Anything else is said too: a thread that died quietly left the window saying "Connecting…" for ever.
                GLib.idle_add(self._refused, f"Could not connect: {failed}")
                return
            connection.log, connection.state, connection.busy = self.log, self.set_state, self.busy
            GLib.idle_add(self._connected, connection, user)
            connection.run()
            if not connection.stopped.is_set():
                GLib.idle_add(self.stop, "The server stopped accepting this computer.")

        threading.Thread(target=work, daemon=True).start()
        return False

    def _refused(self, said: str):
        self.connect_button.set_sensitive(True)
        self.state.set_text("Not connected")
        self.say(said)
        return False

    def _connected(self, connection, user: str):
        self.connection = connection
        self.connect_button.set_sensitive(True)
        self.server.set_text(connection.server)
        self.token.set_text(self.settings.token)
        self.showing(True)
        self.state.set_text(f"Connected as {user}")
        self.log(f"Connected to {connection.server} as {user}", False)
        # On Wayland the desktop asks once whether to allow remote interaction: asked now, while the person who
        # pressed Connect is at the screen, rather than the first time an agent clicks, when they may be away.
        remote = getattr(getattr(connection.runner, "x", None), "remote", None)
        if remote is not None:
            remote.begin()
            self.say("Your desktop may ask whether to allow remote interaction: press Share, with Remember This "
                     "Selection ticked, so your agents can click and type here.")
        return False

    def stop(self, reason: str | None, by_person: bool = False):
        if by_person and self.settings.reconnect:
            self.settings.reconnect = False
            self.settings.save()
        if self.connection is not None:
            self.connection.stop()
            self.connection = None
        self.notice.hide()
        self.showing(False)
        self.state.set_text("Not connected")
        if reason:
            self.say(reason)
            self.log(reason, False)
        return False

    def quit(self):
        from .cli import accessibility_back

        if self.connection is not None:
            self.connection.stop()
        accessibility_back()
        Gtk.main_quit()


def run_window() -> int:
    MainWindow()
    Gtk.main()
    return 0
