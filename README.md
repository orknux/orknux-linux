# Orknux for Linux

Lets your Orknux agents use your own Linux desktop the way you do: list the
windows, start a program, read a window, click, type, press shortcuts, scroll
and take screenshots. It is the Linux half of Orknux for Windows and speaks to
the server through the same door, so an agent given the `desktop_*` tools uses
whichever computer you have connected.

Your agents act as you, on this computer, while it is connected. A strip at
the top of the screen says when one is acting, and **Ctrl+Alt+Q** stops it at
once, wherever the focus is.

## X11 only, for now

Clicking, typing, pressing keys, screenshots and moving windows need an **X11
session**. On Wayland, input from one program to another is not allowed the way
X11 allows it, so Orknux for Linux there can list windows and read them with
`desktop_snapshot`, and refuses the rest in words. On GNOME, choose **GNOME on
Xorg** from the gear on the sign-in screen.

## Install

The accessibility and window toolkits come from your distribution. On Debian
and Ubuntu:

```
sudo apt install python3-gi gir1.2-atspi-2.0 gir1.2-gtk-3.0 at-spi2-core \
                 python3-xlib python3-pil xclip pipx
pipx install --system-site-packages ./orknux-linux
```

`--system-site-packages` is what lets it see `python3-gi`, which is not on
PyPI. `xclip` is needed for text with letters past ASCII (ą, ż, ñ), which is
pasted rather than typed and your clipboard's text put back afterwards.
`pipx inject orknux-linux keyring` keeps the credential in your desktop's
keyring; without it, it is in `~/.config/orknux/credential`, readable only by you.

## Connect

1. In Orknux, open **Preferences › Connected clients** and press **Connect a client**.
2. Start `orknux-linux`, paste the link into **Pairing link or server**, and press **Connect**.

It says **Connected as** you. It reconnects by itself the next time it starts,
unless you pressed **Disconnect** or Ctrl+Alt+Q. An access token with the
server address works in place of a link.

Without a window - a kiosk, a test:

```
orknux-linux --headless --link https://orknux.example.com/pair/K7P-4QX
```

## What an agent can do

Exactly the `desktop_*` tools Orknux for Windows answers, with the same
arguments: `windows`, `open` (a program on the PATH, a file, a folder or an
address, or an app by the name in your app menu; an app already running is
brought forward unless `new` is set), `focus`, `snapshot` (the window's
accessibility tree with refs), `click`, `type`, `press`, `scroll`,
`screenshot` and `close`.

What it reads comes from AT-SPI, so GTK, Qt, Firefox, Chromium (with
accessibility on) and LibreOffice windows can be read. A window from a program
that publishes nothing can still be photographed and clicked by position.

A window screenshot is the screen where the window is, after bringing it
forward: X11 has no way to ask a covered window to paint itself without a
compositor, so the answer says how the picture was taken.

## Checking it

```
test/run.sh
```

Builds a Debian image with Xvfb, openbox and the accessibility bus, runs the
unit tests, then starts the client against a stub Orknux and drives a real GTK
window through every action - including Polish text, the clipboard put back,
and Ctrl+Alt+Q.
