"""Drives the real client through the stub, as an agent's tool calls would, and checks what happened on the desktop."""

import base64
import io
import json
import re
import subprocess
import sys
import time
import urllib.request

from PIL import Image

STUB = sys.argv[1]
failures = 0


def run(action, **arguments):
    request = urllib.request.Request(STUB + "/test/run", data=json.dumps({"action": action, "arguments": arguments}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=90) as answer:
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


def edit_value(text):
    for line in text.splitlines():
        if re.match(r"\[e\d+\] edit", line):
            found = re.search(r'value="([^"]*)"', line)
            return found.group(1) if found else ""
    return None


def clipboard():
    return subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True).stdout.decode()


listed = run("windows")
check("result" in listed and isinstance(listed["result"]["windows"], list), "windows lists the desktop's windows", json.dumps(listed)[:200])

opened = run("open", target="orknux-test-app")
result = opened.get("result", {})
window = result.get("window")
check(result.get("title") == "Orknux test app" and result.get("program") == "orknux-test-app",
      "open starts a program by name and answers its window", json.dumps(opened)[:300])

focused = run("focus", window=window).get("result", {})
check(focused.get("inFront") is True, "focus brings it forward and says so", json.dumps(focused))

snap = run("snapshot", window=window).get("result", {})
text = snap.get("text", "")
button = ref_of(text, "button", "Press me")
edit = ref_of(text, "edit")
check(button is not None and edit is not None and "Not pressed yet" in text,
      "snapshot reads the window: its text, the button and the text box with refs", text[:400])

clicked = run("click", ref=button, window=window)
after = run("snapshot", window=window)["result"]["text"]
check("result" in clicked and "Pressed" in after and "Not pressed yet" not in after,
      "a click on the button's ref presses it", json.dumps(clicked)[:200])

typed = run("type", ref=edit, text="Hello from Orknux", window=window).get("result", {})
value = edit_value(run("snapshot", window=window)["result"]["text"])
check(value == "Hello from Orknux" and typed.get("how") == "typed", "ASCII is typed key by key, exactly", f"{value!r} {typed}")

subprocess.run(["xclip", "-selection", "clipboard", "-i"], input=b"kept before", check=True)
time.sleep(0.2)
polish = run("type", ref=edit, text="zażółć gęślą jaźń", window=window).get("result", {})
value = edit_value(run("snapshot", window=window)["result"]["text"])
check(value == "zażółć gęślą jaźń" and polish.get("how", "").startswith("pasted"),
      "Polish text arrives whole, pasted, replacing what was there", f"{value!r} {polish}")
check(clipboard() == "kept before", "and the clipboard holds what it held before", repr(clipboard()))

pressed = run("press", keys="BackSpace", window=window).get("result", {})
value = edit_value(run("snapshot", window=window)["result"]["text"])
check(pressed.get("pressed") == "Backspace" and value == "zażółć gęślą jaź", "press sends a key to the window", f"{value!r} {pressed}")

shot = run("screenshot", window=window).get("result", {})
image = Image.open(io.BytesIO(base64.b64decode(shot.get("data", "")))) if shot.get("data") else None
check(image is not None and image.format == "JPEG" and image.size == (shot["width"], shot["height"]) and image.size[0] >= 300,
      "a window screenshot is a JPEG of the window's size", json.dumps({k: v for k, v in shot.items() if k != "data"}))
screen = run("screenshot", screen=True).get("result", {})
check((screen.get("width"), screen.get("height")) == (1280, 800), "a screen screenshot is the whole screen",
      json.dumps({k: v for k, v in screen.items() if k != "data"}))

scrolled = run("scroll", window=window, direction="down", amount=3).get("result", {})
check(scrolled == {"scrolled": "down", "notches": 3}, "scroll answers what it did", json.dumps(scrolled))

again = run("open", target="orknux-test-app").get("result", {})
check(again.get("alreadyRunning") is True and again.get("window") == window, "opening it again brings the running one forward", json.dumps(again))

closed = run("close", window=window).get("result", {})
still = [w["window"] for w in run("windows")["result"]["windows"]]
check(closed.get("stillOpen") is False and window not in still, "close closes it", json.dumps(closed))

menu = run("open", target="orknux test").get("result", {})
check(menu.get("fromApplications") == "Orknux Test App" and menu.get("title") == "Orknux test app",
      "a name not on the PATH is found among the menu's apps", json.dumps(menu))
if menu.get("window"):
    run("close", window=menu["window"])

missing = run("open", target="photoshop")
check("error" in missing and "not a program on the PATH" in missing["error"], "an app nobody has is refused in words", json.dumps(missing))

unknown = run("fly")
check("does not know the action" in unknown.get("error", ""), "an unknown action is refused in words", json.dumps(unknown))

print("ALL PASSED" if failures == 0 else f"{failures} FAILED", flush=True)
sys.exit(1 if failures else 0)
