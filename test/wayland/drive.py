"""Drives the real client on a GNOME Wayland desktop through the stub, as an agent's tool calls would."""

import base64
import io
import json
import re
import sys
import time
import urllib.request

from PIL import Image

from orknux_linux.desktop import atspi

STUB = sys.argv[1]
failures = 0
atspi.init()


def run(action, **arguments):
    request = urllib.request.Request(STUB + "/test/run", data=json.dumps({"action": action, "arguments": arguments}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=200) as answer:
        return json.loads(answer.read())


def check(ok, what, detail=""):
    global failures
    print(f"{'PASS' if ok else 'FAIL'} {what}" + (f" - {detail}" if detail else ""), flush=True)
    if not ok:
        failures += 1


def ref_of(text, role, name=None):
    for line in text.splitlines():
        match = re.match(r"\[(e\d+)\] (\w+)(?: \"([^\"]*)\")?", line)
        if match and match.group(2) == role and (name is None or match.group(3) == name):
            return match.group(1)
    return None


def entry_text():
    """What the test app's text box holds, read the way a person's eyes would not need to: through accessibility."""
    for _, frame in atspi.frames():
        if atspi.name_of(frame) == "Orknux test app":
            for element in atspi.walk(frame):
                if atspi.role_of(element) == "edit":
                    return atspi.text_of(element), element
    return None, None


def snapshot(window):
    return run("snapshot", window=window).get("result", {}).get("text", "")


listed = run("windows")
check("Wayland" in listed.get("result", {}).get("note", ""), "windows says it is a Wayland desktop", json.dumps(listed)[:240])

opened = run("open", target="orknux-test-app")
result = opened.get("result", {})
window = result.get("window")
check(result.get("title") == "Orknux test app" and result.get("program") == "orknux-test-app",
      "open starts a program by name and answers its window", json.dumps(opened)[:300])

read = snapshot(window)
button, edit = ref_of(read, "button", "Press me"), ref_of(read, "edit")
check("Not pressed yet" in read and button and edit, "snapshot reads the window: its text, the button and the text box with refs", read[:300])

clicked = run("click", ref=button, window=window)
check("Pressed" in snapshot(window) and "accessible action" in clicked.get("result", {}).get("how", ""),
      "a click on the button's ref presses it, by its accessible action", json.dumps(clicked)[:240])

typed = run("type", ref=edit, text="zażółć gęślą jaźń", window=window)
value, element = entry_text()
check(value == "zażółć gęślą jaźń" and typed.get("result", {}).get("how") == "set through accessibility",
      "Polish text arrives whole, through accessibility, with no clipboard", f"{value!r} {typed.get('result')}")

run("type", ref=edit, text=" i więcej", append=True, window=window)
value, _ = entry_text()
check(value == "zażółć gęślą jaźń i więcej", "append keeps what was there", repr(value))

# The person clicks into the box - which selects what it holds, as GTK does - and presses End.
atspi.grab_focus(element)
time.sleep(0.3)
run("press", keys="End", window=window)
def state(label):
    seen = []
    for _, frame in atspi.frames():
        focused = [f"{atspi.role_of(e)}:{atspi.name_of(e)!r}" for e in atspi.walk(frame, 30) if atspi.has_state(e, "FOCUSED")]
        seen.append(f"{atspi.name_of(frame)!r} active={atspi.has_state(frame, 'ACTIVE')} focused={focused}")
    print(f"STATE {label}: " + " | ".join(seen), flush=True)


state("before typing")
keyed = run("type", text=" +ok ą", window=window)
state("after typing")
time.sleep(0.3)
value, _ = entry_text()
check(value == "zażółć gęślą jaźń i więcej +ok ą" and "caret" in keyed.get("result", {}).get("how", ""),
      "typing with no ref goes where the focus is, at the caret, Polish letters included", f"{value!r} {keyed}")

pressed = run("press", keys="Backspace", window=window)
time.sleep(0.3)
value, _ = entry_text()
check(value == "zażółć gęślą jaźń i więcej +ok " and pressed.get("result", {}).get("pressed") == "Backspace",
      "press sends a key to the window through the portal", f"{value!r} {pressed}")

screen = run("screenshot", screen=True).get("result", {})
picture = Image.open(io.BytesIO(base64.b64decode(screen.get("data", "")))) if screen.get("data") else None
check(picture is not None and picture.size == (1280, 800) and screen.get("mimeType") == "image/jpeg",
      "a screen screenshot is the whole screen, from the session's own screen cast", json.dumps({k: v for k, v in screen.items() if k != "data"}))
dark = picture is not None and max(picture.convert("L").getextrema()) > 40
check(dark, "and it shows something rather than black")

shot = run("screenshot", window=window).get("result", {})
check(shot.get("width") == 1280 and "Wayland" in shot.get("how", ""),
      "a window screenshot says why it is the whole screen", json.dumps({k: v for k, v in shot.items() if k != "data"}))

scrolled = run("scroll", window=window, direction="down", amount=2)
check(scrolled.get("result", {}).get("scrolled") == "down", "scroll answers what it did", json.dumps(scrolled))

pointed = run("click", x=640, y=400)
check(pointed.get("result", {}).get("at") == [640, 400], "a click at a point goes through the portal's pointer", json.dumps(pointed))

again = run("open", target="orknux-test-app")
check(again.get("result", {}).get("window") == window and again.get("result", {}).get("alreadyRunning"),
      "opening it again finds the running one", json.dumps(again)[:240])

closed = run("close", window=window)
check(closed.get("result", {}).get("stillOpen") is False, "close closes it", json.dumps(closed))

refused = run("open", target="photoshop")
check("photoshop" in refused.get("error", ""), "an app nobody has is refused in words", json.dumps(refused))

print("ALL PASSED" if failures == 0 else f"{failures} FAILED", flush=True)
sys.exit(1 if failures else 0)
