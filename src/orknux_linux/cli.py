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
from .core.errors import ConnectionRefused
from .settings import Settings


def connect(server: str, secret: str, settings: Settings, log=print) -> tuple[Connection, str]:
    """Pairs when given a link or a code, says hello, and saves what worked."""
    from .desktop.runner import make_runner

    server, secret, is_code = pairing.resolve(server, secret)
    if not server:
        raise ConnectionRefused("Paste the pairing link from Orknux: Preferences › Connected clients › Connect a client.")
    if is_code:
        secret = pairing.trade(server, secret)
    connection = Connection(server, secret, VERSION, make_runner(), log=lambda line, failed: log(("! " if failed else "") + line))
    user = connection.hello()
    settings.server, settings.token, settings.reconnect = server, secret, True
    settings.save()
    return connection, user


def headless(arguments) -> int:
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
    if not arguments.no_hotkey and os.environ.get("DISPLAY"):
        from .desktop.x11 import StopHotkey

        def pressed():
            print("Stopped with Ctrl+Alt+Q.", flush=True)
            settings.reconnect = False
            settings.save()
            connection.stop()

        try:
            StopHotkey(pressed)
        except Exception as failed:
            print(f"! Ctrl+Alt+Q could not be claimed: {failed}", file=sys.stderr)
    worker = threading.Thread(target=connection.run, daemon=True)
    worker.start()
    while worker.is_alive():
        worker.join(0.5)
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
