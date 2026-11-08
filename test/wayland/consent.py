"""The person at the desk: answers the desktop's questions as somebody letting Orknux for Linux in would.

GNOME asks in two kinds of dialog. The portal's own windows (Remote Desktop,
a global shortcut) are GTK, with buttons that have an accessible action; this
presses their yes, with remote interaction switched on. GNOME Shell's dialogs
("Allow Apps to Take Screenshots?") are drawn by the shell, whose buttons have
no action but do say where they are on the screen, so they are clicked with a
pointer of this script's own - which asks a Remote Desktop question of its own
first, answered by the same loop. Runs until killed, and prints what it
answered, so a run shows which questions were asked.
"""

import threading
import time

from orknux_linux.desktop import atspi

YES = ("Share", "Allow", "Add", "Continue", "Confirm", "Install")
answered: set = set()
pointer = {"desk": None, "busy": False}

atspi.init()


def press_shell_button(element, label: str):
    def go():
        try:
            if pointer["desk"] is None:
                from orknux_linux.desktop.wayland import Wayland

                pointer["desk"] = Wayland()
            x, y, width, height = atspi.extents(element)
            pointer["desk"].click(x + width // 2, y + height // 2)
            print(f"consent: clicked {label!r} on GNOME Shell's dialog", flush=True)
        except Exception as failed:  # noqa: BLE001
            print(f"consent: could not click {label!r}: {failed}", flush=True)
        finally:
            pointer["busy"] = False

    pointer["busy"] = True
    threading.Thread(target=go, daemon=True).start()


while True:
    for key, _pid, frame in atspi.frames_by_key():
        shell = atspi.name_of(frame) == "Main stage"
        elements = list(atspi.walk(frame, 30 if shell else 14))
        if shell:
            if pointer["busy"]:
                continue
            yes = next((e for e in elements if atspi.role_of(e) == "button" and atspi.name_of(e) == "Allow"
                        and atspi.has_state(e, "SHOWING") and atspi.extents(e)), None)
            if yes is not None and (key, atspi.extents(yes)) not in answered:
                answered.add((key, atspi.extents(yes)))
                press_shell_button(yes, "Allow")
            continue
        if key in answered:
            continue
        yes = next((e for e in elements if atspi.role_of(e) == "button" and atspi.name_of(e) in YES
                    and atspi.has_state(e, "SENSITIVE")), None)
        if yes is None:
            continue
        for switch in elements:
            if atspi.role_of(switch) == "switch" and "Remote Interaction" in atspi.name_of(switch) \
                    and not atspi.has_state(switch, "CHECKED") and "toggle" in atspi.actions_of(switch):
                atspi.do_action(switch, ("toggle",))
        time.sleep(0.3)
        if atspi.do_action(yes, ("click",)):
            answered.add(key)
            print(f"consent: pressed {atspi.name_of(yes)!r} on {atspi.name_of(frame)!r}", flush=True)
    time.sleep(0.2)
