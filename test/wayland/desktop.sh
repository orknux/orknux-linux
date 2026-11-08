#!/bin/bash
# Starts a GNOME Wayland session with nobody at it, inside dbus-run-session, then runs "$@" in it.
set -u
# GNOME Shell asks the system bus for logind and its time limits; one with nothing on it is enough.
if [ ! -S /run/dbus/system_bus_socket ]; then mkdir -p /run/dbus; dbus-daemon --system --fork; fi
export XDG_RUNTIME_DIR=/tmp/runtime-$(id -u) HOME=/root XDG_CONFIG_HOME=/root/.config
mkdir -p -m 700 "$XDG_RUNTIME_DIR"
export XDG_SESSION_TYPE=wayland XDG_CURRENT_DESKTOP=GNOME XDG_SESSION_DESKTOP=gnome GSETTINGS_BACKEND=memory
# The portals choose their backend by XDG_CURRENT_DESKTOP, and are started by the bus: it has to know it.
dbus-update-activation-environment XDG_CURRENT_DESKTOP XDG_SESSION_TYPE XDG_SESSION_DESKTOP XDG_RUNTIME_DIR GSETTINGS_BACKEND HOME
pipewire >/tmp/pipewire.log 2>&1 &
sleep 0.5
wireplumber >/tmp/wireplumber.log 2>&1 &
/usr/libexec/at-spi-bus-launcher --launch-immediately >/tmp/atspi.log 2>&1 &
gnome-shell --headless --wayland --no-x11 --virtual-monitor 1280x800 ${GNOME_SHELL_FLAGS:-} >/tmp/shell.log 2>&1 &
for _ in $(seq 100); do [ -S "$XDG_RUNTIME_DIR/wayland-0" ] && break; sleep 0.1; done
export WAYLAND_DISPLAY=wayland-0
dbus-update-activation-environment WAYLAND_DISPLAY
for _ in $(seq 100); do gdbus introspect --session --dest org.gnome.Shell --object-path /org/gnome/Shell >/dev/null 2>&1 && break; sleep 0.1; done
"$@"
