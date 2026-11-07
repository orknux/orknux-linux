#!/bin/bash
# Runs inside the test image, under dbus-run-session: a desktop on Xvfb with the accessibility bus,
# a stub Orknux, the client paired by link, and the driver. Then Ctrl+Alt+Q, pressed as a person would.
set -u
export DISPLAY=:99 HOME=/tmp/home XDG_CONFIG_HOME=/tmp/home/.config
mkdir -p "$HOME"
Xvfb :99 -screen 0 1280x800x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
for _ in $(seq 50); do xdpyinfo >/dev/null 2>&1 && break; sleep 0.1; done
openbox >/tmp/openbox.log 2>&1 &
/usr/libexec/at-spi-bus-launcher --launch-immediately >/tmp/atspi.log 2>&1 &
sleep 1

echo "== unit tests"
python3 -m pytest -q /src/tests 2>&1 | tail -3
unit=${PIPESTATUS[0]}

echo "== the client on a desktop"
PORT=8777
python3 /src/test/stub_server.py $PORT &
sleep 0.5
python3 -m orknux_linux.cli --headless --link "http://127.0.0.1:$PORT/pair/abc-def" >/tmp/client.log 2>&1 &
client=$!
for _ in $(seq 50); do grep -q "Connected" /tmp/client.log && break; sleep 0.1; done
head -1 /tmp/client.log
python3 /src/test/drive.py "http://127.0.0.1:$PORT"
drive=$?

echo "== Ctrl+Alt+Q"
python3 - <<'EOF'
from Xlib import X, XK, display
from Xlib.ext import xtest
d = display.Display()
codes = [d.keysym_to_keycode(XK.string_to_keysym(k)) for k in ("Control_L", "Alt_L", "q")]
for c in codes: xtest.fake_input(d, X.KeyPress, c)
for c in reversed(codes): xtest.fake_input(d, X.KeyRelease, c)
d.sync()
EOF
for _ in $(seq 100); do kill -0 $client 2>/dev/null || break; sleep 0.1; done
hotkey=0
if kill -0 $client 2>/dev/null; then echo "FAIL Ctrl+Alt+Q did not stop the client"; hotkey=1; kill $client
elif ! grep -q "Stopped with Ctrl+Alt+Q" /tmp/client.log; then echo "FAIL the client stopped without saying why"; hotkey=1
elif ! python3 -c "import json,sys; sys.exit(0 if json.load(open('$XDG_CONFIG_HOME/orknux/desktop.json'))['reconnect'] is False else 1)"; then
  echo "FAIL a stop by Ctrl+Alt+Q left it set to reconnect"; hotkey=1
else echo "PASS Ctrl+Alt+Q stops the agent at once, and the next start does not reconnect"; fi
stat -c '%a' "$XDG_CONFIG_HOME/orknux/credential" 2>/dev/null | grep -q 600 && echo "PASS the credential is kept readable only by this account" || { echo "FAIL the credential file is not mode 600"; hotkey=1; }

echo "== the window"
timeout 5 python3 -c "
import gi; gi.require_version('Gtk','3.0')
from gi.repository import Gtk, GLib
from orknux_linux.app import MainWindow
w = MainWindow(); title = w.get_title(); GLib.timeout_add(500, Gtk.main_quit); Gtk.main()
print('PASS the window opens, titled', title) if title.endswith('1.0.0') else print('FAIL the window title', title)
" 2>&1 | grep -E "PASS|FAIL|Error" | head -3

if [ $unit -eq 0 ] && [ $drive -eq 0 ] && [ $hotkey -eq 0 ]; then echo "ALL CHECKS PASSED"; exit 0; fi
echo "CLIENT LOG:"; cat /tmp/client.log
exit 1
