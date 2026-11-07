#!/bin/bash
# The whole check: unit tests, then the client driving a real GTK window on a headless desktop
# through the same long poll an Orknux server uses. Needs Docker; nothing else on this machine.
set -e
here="$(cd "$(dirname "$0")/.." && pwd)"
docker build -q -t orknux-linux-test -f "$here/test/Dockerfile" "$here" >/dev/null
docker run --rm -v "$here:/src:ro" orknux-linux-test dbus-run-session -- bash /src/test/inside.sh
