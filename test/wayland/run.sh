#!/bin/bash
# The Wayland check: the client on a real GNOME Shell (headless, a virtual monitor) through its portals,
# driving a GTK window, with the person's answers to GNOME's questions given through accessibility.
set -e
here="$(cd "$(dirname "$0")/../.." && pwd)"
docker build -q -t orknux-linux-wayland -f "$here/test/wayland/Dockerfile" "$here" >/dev/null
docker run --rm -v "$here:/src:ro" orknux-linux-wayland dbus-run-session -- /src/test/wayland/desktop.sh bash /src/test/wayland/inside.sh
