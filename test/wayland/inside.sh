#!/bin/bash
# Runs inside the Wayland test image, in the GNOME session desktop.sh starts: a stub Orknux, the person
# answering GNOME's questions, the client paired by link, the driver, then Ctrl+Alt+Q pressed as a person would.
set -u
export PYTHONPATH=/src/src
export XDG_CONFIG_HOME=/tmp/home/.config
mkdir -p "$XDG_CONFIG_HOME"

python3 /src/test/wayland/consent.py >/tmp/consent.log 2>&1 &
consent=$!

echo "== the client on a GNOME Wayland desktop"
PORT=8777
python3 /src/test/stub_server.py $PORT &
sleep 0.5
python3 -m orknux_linux.cli --headless --link "http://127.0.0.1:$PORT/pair/abc-def" >/tmp/client.log 2>&1 &
client=$!
for _ in $(seq 100); do grep -q "Connected" /tmp/client.log && break; sleep 0.1; done
head -1 /tmp/client.log
python3 /src/test/wayland/drive.py "http://127.0.0.1:$PORT"
drive=$?

echo "== the desktop's questions"
cat /tmp/consent.log
python3 -c "import json,sys; sys.exit(0 if json.load(open('$XDG_CONFIG_HOME/orknux/desktop.json')).get('portalToken') else 1)" \
  && echo "PASS the desktop's yes is kept, so it is not asked again" || { echo "FAIL no restore token was kept"; drive=1; }
stat -c '%a' "$XDG_CONFIG_HOME/orknux/desktop.json" | grep -q 600 \
  && echo "PASS the file it is kept in is readable only by this account" || { echo "FAIL desktop.json is not mode 600"; drive=1; }

echo "== Ctrl+Alt+Q"
python3 - <<'EOF'
import time
from orknux_linux.desktop.portal import Portal, RemoteControl
from orknux_linux.desktop.wayland import Wayland

keys = Wayland(portal=Portal())
names = ["Control_L", "Alt_L", "q"]
keys.chord(names)
time.sleep(0.5)
EOF
for _ in $(seq 100); do kill -0 $client 2>/dev/null || break; sleep 0.1; done
hotkey=0
if kill -0 $client 2>/dev/null; then echo "FAIL Ctrl+Alt+Q did not stop the client"; hotkey=1; kill $client
elif ! grep -q "Stopped with Ctrl+Alt+Q" /tmp/client.log; then echo "FAIL the client stopped without saying why"; hotkey=1
else echo "PASS Ctrl+Alt+Q stops the agent at once, through the GlobalShortcuts portal"; fi
echo "== a second start"
# Counted from here: the Ctrl+Alt+Q above was pressed through a session of the test's own, which asked too.
before=$(grep -c "on 'Remote Desktop'" /tmp/consent.log)
python3 -m orknux_linux.cli --headless --no-hotkey >/tmp/client2.log 2>&1 &
client=$!
for _ in $(seq 100); do grep -q "Connected" /tmp/client2.log && break; sleep 0.1; done
again=$(python3 -c "
import json, urllib.request
r = urllib.request.Request('http://127.0.0.1:$PORT/test/run', json.dumps({'action': 'press', 'arguments': {'keys': 'Escape'}}).encode(), {'Content-Type': 'application/json'})
print(urllib.request.urlopen(r, timeout=200).read().decode())")
asked=$(( $(grep -c "on 'Remote Desktop'" /tmp/consent.log) - before ))
if echo "$again" | grep -q '"pressed"' && [ "$asked" -eq 0 ]; then
  echo "PASS a second start acts at once on the kept answer, without asking again"
else echo "FAIL a second start: $again, Remote Desktop asked $asked more times"; hotkey=1; fi
kill $client 2>/dev/null
kill $consent 2>/dev/null

if [ $drive -eq 0 ] && [ $hotkey -eq 0 ]; then echo "ALL WAYLAND CHECKS PASSED"; exit 0; fi
echo "CLIENT LOG:"; cat /tmp/client.log
exit 1
