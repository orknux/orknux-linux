"""Pairs the window through accessibility - the link typed into its field, Connect pressed - as a person would."""
import sys, time
sys.path.insert(0, "/src/src")
from orknux_linux.desktop import atspi

LINK = sys.argv[1]
atspi.init()
frame = None
for _ in range(200):
    for _, candidate in atspi.frames():
        if atspi.name_of(candidate).startswith("Orknux for Linux"):
            frame = candidate
    if frame is not None:
        break
    time.sleep(0.1)
if frame is None:
    sys.exit("no Orknux for Linux window")
entries = [e for e in atspi.walk(frame) if atspi.role_of(e) in ("edit", "entry", "text")]
buttons = [e for e in atspi.walk(frame) if atspi.role_of(e) == "button" and atspi.name_of(e) == "Connect"]
print("entries", len(entries), "connect buttons", len(buttons), flush=True)
if not entries or not buttons:
    sys.exit("the window's field or button was not found through accessibility")
atspi.set_text(entries[0], LINK, False)
print("pressed:", atspi.do_action(buttons[0], ("click", "press", "activate")), flush=True)
