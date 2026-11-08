"""orknux-linux: the window by default, or --headless for a session with nobody at it - a test, a kiosk.

  orknux-linux                                   the window
  orknux-linux --headless --link <pairing link>  pair, then serve
  orknux-linux --headless --server URL --token orkx_...
  orknux-linux --headless                        the saved server and credential

ORKNUX_SERVER and ORKNUX_TOKEN stand in for the flags.
"""

import argparse
import os
import signal
import sys
import threading

from . import VERSION
from .core import pairing
from .core.connection import Connection
from .core.errors import ConnectionRefused, Refused
from .settings import Settings


def connect(server: str, secret: str, settings: Settings, log=print) -> tuple[Connection, str]:
    """Pairs when given a link or a code, says hello, and saves what worked."""
    from .desktop.runner import make_runner

    server, secret, is_code = pairing.resolve(server, secret)
    if not server:
        raise ConnectionRefused("Paste the pairing link from Orknux: Preferences › Connected clients › Connect a client.")
    if is_code:
        secret = pairing.trade(server, secret)
    try:
        runner = make_runner(settings=settings)
    except Refused as refused:
        # Nothing to lend the server: said where the person connects, rather than lost on the connecting thread.
        raise ConnectionRefused(str(refused)) from None
    connection = Connection(server, secret, VERSION, runner, log=lambda line, failed: log(("! " if failed else "") + line))
    user = connection.hello()
    settings.server, settings.token, settings.reconnect = server, secret, True
    settings.save()
    return connection, user


_accessibility_was: list = []


def accessibility_on():
    """Every program started from now on publishes what it shows; put back as it was on the way out."""
    from .desktop import atspi

    _accessibility_was.append(atspi.enable_accessibility())


def accessibility_back():
    from .desktop import atspi

    if _accessibility_was and _accessibility_was[0] is False:
        try:
            atspi.set_accessibility(False)
        except Exception:
            pass


def claim_stop_key(pressed) -> str | None:
    """Ctrl+Alt+Q: grabbed on X11, through the GlobalShortcuts portal on Wayland. Why not, or None."""
    from .desktop.session import session_is_wayland

    try:
        if session_is_wayland():
            from .desktop.portal import StopShortcut

            shortcut = StopShortcut(pressed)
            shortcut.ready.wait(200)
            return shortcut.failed
        if not os.environ.get("DISPLAY"):
            return "there is no display"
        try:
            from .desktop import x11
        except ImportError:
            return "the python-xlib that comes with Orknux for Linux is missing: install Orknux for Linux again"
        x11.StopHotkey(pressed)
        return None
    except Exception as failed:  # noqa: BLE001
        return str(failed)


def headless(arguments) -> int:
    from .desktop.session import SSH_WARNING, forwarded_over_ssh

    if forwarded_over_ssh():
        print(f"! {SSH_WARNING}", file=sys.stderr)
    accessibility_on()
    settings = Settings.load()
    server = arguments.link or arguments.server or os.environ.get("ORKNUX_SERVER") or settings.server
    secret = arguments.token or os.environ.get("ORKNUX_TOKEN") or ("" if arguments.link else settings.token)
    try:
        connection, user = connect(server, secret, settings)
    except ConnectionRefused as refused:
        print(f"Not connected: {refused}", file=sys.stderr)
        return 2
    print(f"Connected to {connection.server} as {user}", flush=True)

    def stop(*_):
        connection.stop()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if not arguments.no_hotkey:
        def pressed():
            print("Stopped with Ctrl+Alt+Q.", flush=True)
            settings.reconnect = False
            settings.save()
            connection.stop()

        said = claim_stop_key(pressed)
        if said:
            print(f"! Ctrl+Alt+Q could not be claimed: {said}", file=sys.stderr)
    worker = threading.Thread(target=connection.run, daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            worker.join(0.5)
    finally:
        accessibility_back()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="orknux-linux", description="Lend this Linux desktop to your Orknux agents.")
    parser.add_argument("--headless", action="store_true", help="no window: connect and serve until stopped")
    parser.add_argument("--link", help="a pairing link from Orknux: <server>/pair/<code>")
    parser.add_argument("--server", help="the Orknux server's address")
    parser.add_argument("--token", help="a pairing code or an access token")
    parser.add_argument("--no-hotkey", action="store_true", help="do not claim Ctrl+Alt+Q")
    parser.add_argument("--version", action="version", version=f"Orknux for Linux {VERSION}")
    arguments = parser.parse_args(argv)
    if arguments.headless:
        return headless(arguments)
    from .app import run_window

    return run_window()


if __name__ == "__main__":
    sys.exit(main())
