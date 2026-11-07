# A Linux desktop with nobody at it: Xvfb, openbox, the AT-SPI bus, GTK 3, and what the client needs.
FROM debian:bookworm
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      python3 python3-gi gir1.2-atspi-2.0 gir1.2-gtk-3.0 at-spi2-core libatk-adaptor \
      python3-xlib python3-pil python3-pytest \
      xvfb x11-utils openbox xclip dbus dbus-x11 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY test/orknux-test-app /usr/local/bin/orknux-test-app
RUN chmod +x /usr/local/bin/orknux-test-app && mkdir -p /usr/share/applications && printf '%s\n' \
      '[Desktop Entry]' 'Type=Application' 'Name=Orknux Test App' 'Exec=/usr/local/bin/orknux-test-app %U' \
      > /usr/share/applications/orknux-test.desktop
ENV PYTHONPATH=/src/src
WORKDIR /src
