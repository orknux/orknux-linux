#!/bin/bash
# A picture of Orknux for Linux for the manual: its window on the headless GNOME desktop the Wayland check
# runs on, connected to the stand-in server from saved settings as a second start would be, photographed by
# GNOME Shell itself (which needs --unsafe-mode to answer an unprivileged caller). Written to /out/linux-screen.png.
set -u
export PYTHONPATH=/src/src
export XDG_CONFIG_HOME=/tmp/home/.config
mkdir -p "$XDG_CONFIG_HOME/orknux"
PORT=8777
python3 /src/test/stub_server.py $PORT &
sleep 0.5
# What a first start would have saved: the server, the wish to reconnect, and the credential the stub hands out.
printf '{"server": "http://127.0.0.1:%s", "reconnect": true}\n' "$PORT" > "$XDG_CONFIG_HOME/orknux/desktop.json"
python3 -c "import re; print(re.search(r'CREDENTIAL\s*=\s*[\"\']([^\"\']+)', open('/src/test/stub_server.py').read()).group(1))" > "$XDG_CONFIG_HOME/orknux/credential"
chmod 600 "$XDG_CONFIG_HOME/orknux/credential"
python3 /src/test/wayland/consent.py >/tmp/consent.log 2>&1 &
python3 -m orknux_linux.cli --no-hotkey >/tmp/client.log 2>&1 &
sleep 14
# A fresh session opens in the overview; the window is photographed on the desktop, not among previews.
gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell --method org.gnome.Shell.Eval 'Main.overview.hide()' >/dev/null
sleep 2
gdbus call --session --dest org.gnome.Shell.Screenshot --object-path /org/gnome/Shell/Screenshot \
  --method org.gnome.Shell.Screenshot.Screenshot false false /out/linux-screen.png && echo "wrote /out/linux-screen.png (GNOME Shell)"
head -5 /tmp/client.log
