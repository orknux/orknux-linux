# A GNOME Wayland desktop with nobody at it: GNOME Shell headless on a virtual monitor, PipeWire for the
# portals' screen casts, xdg-desktop-portal-gnome, the accessibility bus, and what the client needs.
FROM ubuntu:26.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      gnome-shell mutter xdg-desktop-portal xdg-desktop-portal-gnome pipewire wireplumber \
      dbus dbus-x11 at-spi2-core libatk-adaptor gir1.2-atspi-2.0 gir1.2-gtk-3.0 \
      python3 python3-gi python3-pil python3-pytest fonts-dejavu-core gsettings-desktop-schemas \
      libglib2.0-bin gstreamer1.0-pipewire gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base gir1.2-gst-plugins-base-1.0 \
    && rm -rf /var/lib/apt/lists/*
COPY test/orknux-test-app /usr/local/bin/orknux-test-app
RUN chmod +x /usr/local/bin/orknux-test-app && mkdir -p /usr/share/applications && printf '%s\n' \
      '[Desktop Entry]' 'Type=Application' 'Name=Orknux Test App' 'Exec=/usr/local/bin/orknux-test-app %U' \
      > /usr/share/applications/orknux-test.desktop
RUN useradd -m tester

ENV PYTHONPATH=/src/src
WORKDIR /src
# No logind in a container: without its activation file GNOME Shell sees none rather than one that fails to start.
RUN rm -f /usr/share/dbus-1/system-services/org.freedesktop.login1.service /usr/share/dbus-1/system-services/org.freedesktop.timedate1.service
