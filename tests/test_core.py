import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from orknux_linux.core import appnames, keychord, pairing
from orknux_linux.core.connection import Connection, describe
from orknux_linux.core.errors import ConnectionRefused, Refused
from orknux_linux.core.snapshot import RefTable, SnapNode, lines_of, render

# ---- pairing links ----


@pytest.mark.parametrize("link, server, code", [
    ("http://192.168.0.190:8098/pair/U7N-HQE", "http://192.168.0.190:8098", "U7N-HQE"),
    ("https://orknux.example.com/pair/k7pqx4", "https://orknux.example.com", "k7pqx4"),
    ("https://example.com/orknux/pair/K7P-4QX/", "https://example.com/orknux", "K7P-4QX"),
    ("  http://h:1/pair/ABC-DEF  ", "http://h:1", "ABC-DEF"),
])
def test_a_pairing_link_gives_the_server_and_the_code(link, server, code):
    assert pairing.parse_link(link) == (server, code)


@pytest.mark.parametrize("text", ["K7P-4QX", "http://h/pair/", "ftp://h/pair/ABC-DEF", "http://h/pair/ABC-DE1O", "garbage"])
def test_what_is_not_a_link_is_not_taken_for_one(text):
    assert pairing.parse_link(text) is None


def test_either_field_may_hold_the_link_and_a_code_is_told_from_a_token():
    assert pairing.resolve("", "http://h:1/pair/ABC-DEF") == ("http://h:1", "ABC-DEF", True)
    assert pairing.resolve("http://h:1/", "k7p-4qx") == ("http://h:1", "k7p-4qx", True)
    assert pairing.resolve("http://h:1", "orkx_abc") == ("http://h:1", "orkx_abc", False)


# ---- app names ----

MENU = ["Musigium", "Uninstall Musigium", "Musigium Setup", "MuseScore 4", "Text Editor", "gedit",
        "LibreOffice Writer", "LibreOffice Calc", "Visual Studio Code", "KeePassXC"]


def test_an_app_is_found_by_the_name_a_person_would_type():
    assert appnames.best("musigium", MENU) == "Musigium"
    assert appnames.best("Musigium", reversed(MENU)) == "Musigium"


def test_a_word_inside_the_name_finds_it():
    assert appnames.best("writer", MENU) == "LibreOffice Writer"
    assert appnames.best("studio code", MENU) == "Visual Studio Code"


def test_an_uninstaller_only_when_asked_for_and_nothing_for_an_unknown_name():
    assert appnames.best("uninstall musigium", MENU) == "Uninstall Musigium"
    assert appnames.best("photoshop", MENU) is None
    assert "MuseScore 4" in appnames.near("musescore studio", MENU)


@pytest.mark.parametrize("asked, program, same", [
    ("musigium", "Musigium", True), ("MuseScore", "mscore4", False), ("musescore 4", "MuseScore4", True),
    ("gedit", "gedit", True), ("gedit", "gedit-plugins", False), ("code", "codex", False), ("x", None, False),
])
def test_a_running_program_is_the_app_only_by_its_own_name(asked, program, same):
    assert appnames.is_program(asked, program) is same


# ---- keys ----


@pytest.mark.parametrize("written, said, keysyms", [
    ("ctrl+t", "Ctrl+T", ["Control_L", "t"]),
    ("Ctrl+Shift+S", "Ctrl+Shift+S", ["Control_L", "Shift_L", "s"]),
    ("enter", "Enter", ["Return"]),
    ("Alt+F4", "Alt+F4", ["Alt_L", "F4"]),
    ("ctrl++", "Ctrl++", ["Control_L", "plus"]),
    ("PgDn", "PageDown", ["Next"]),
    ("win", "Win", ["Super_L"]),
    ("Backspace", "Backspace", ["BackSpace"]),
])
def test_a_key_chord_is_read_and_pressed_as_x11_names_it(written, said, keysyms):
    chord = keychord.parse(written)
    assert str(chord) == said
    assert chord.keysyms() == keysyms


@pytest.mark.parametrize("written", ["", "hyper+x", "ctrl+banana"])
def test_what_is_not_a_key_is_refused_in_words(written):
    with pytest.raises(Refused):
        keychord.parse(written)


# ---- snapshots ----


def test_a_snapshot_reads_like_the_windows_one():
    table = RefTable()
    root = SnapNode("frame", "Orknux test app", children=[
        SnapNode("header", "Settings"),
        SnapNode("text", "Type below"),
        SnapNode("button", "Press me", ref=table.add("b")),
        SnapNode("edit", "", value="zażółć", states=["focused"], ref=table.add("e")),
        SnapNode("button", "Off", states=["disabled"], ref=table.add("d"), children=[SnapNode("text", "inside")]),
    ])
    lines = lines_of(root, interactive_only=False)
    assert lines == ['heading "Settings"', "Type below", '[e1] button "Press me"',
                     '[e2] edit value="zażółć" (focused)', '[e3] button "Off" (disabled)']
    assert lines_of(root, interactive_only=True) == lines[2:]
    rendered = render(42, "Orknux test app", lines, None, 20_000)
    assert rendered["text"].startswith("Window: Orknux test app\nId: 42\n")
    assert table.resolve("E2") == "e"
    with pytest.raises(Refused):
        table.resolve("e9")


def test_a_long_snapshot_is_cut_and_says_so_and_find_narrows_it():
    lines = [f'[e{n}] button "Button {n}"' for n in range(1, 200)]
    cut = render(1, "Big", lines, None, 600)
    assert len(cut["text"]) <= 600 and "more lines were cut" in cut["cut"]
    found = render(1, "Big", lines, "Button 150", 20_000)
    assert found["text"].count("\n") == 3
    assert "Nothing in the window" in render(1, "Big", lines, "nowhere", 20_000)["note"]


# ---- the protocol, against a stub server ----


class Stub:
    def __init__(self):
        self.queue = [{"id": "c1", "action": "windows", "arguments": {}},
                      {"id": "c2", "action": "fly", "arguments": {}}]
        self.answers = {}
        self.paired = []
        self.seen_auth = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _json(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                stub.seen_auth.append(self.headers.get("Authorization"))
                if self.path.startswith("/api/client/compatibility"):
                    return self._json(200, {"compatible": True})
                if self.headers.get("Authorization") != "Bearer orkxc_good":
                    return self._json(401, {"error": "no"})
                if self.path == "/api/desktop/hello":
                    return self._json(200, {"user": "alice"})
                if self.path.startswith("/api/desktop/next"):
                    if stub.queue:
                        return self._json(200, stub.queue.pop(0))
                    self.send_response(204)
                    self.end_headers()
                    return None
                return self._json(404, {})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if self.path == "/api/clients/pair":
                    stub.paired.append(body)
                    if body.get("code", "").upper() == "ABC-DEF":
                        return self._json(200, {"credential": "orkxc_good", "user": "alice"})
                    return self._json(400, {"error": "That pairing code is not valid."})
                if self.path.startswith("/api/desktop/answers/"):
                    stub.answers[self.path.rsplit("/", 1)[1]] = body
                    self.send_response(204)
                    self.end_headers()
                    return None
                return self._json(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


class FakeRunner:
    def run(self, action, args):
        if action == "windows":
            return {"windows": [{"window": 7, "title": "Notepad"}]}
        raise Refused(f'Orknux for Linux does not know the action "{action}".')


def test_a_code_is_traded_and_the_credential_answers_commands():
    stub = Stub()
    credential = pairing.trade(stub.url, "abc-def", name="Linux on test")
    assert credential == "orkxc_good"
    assert stub.paired[0] == {"code": "abc-def", "client": "Linux", "name": "Linux on test"}
    with pytest.raises(ConnectionRefused, match="not valid"):
        pairing.trade(stub.url, "XXX-YYY")

    logged = []
    connection = Connection(stub.url, credential, "1.0.0", FakeRunner(), log=lambda line, failed: logged.append((line, failed)))
    assert connection.hello() == "alice"
    worker = threading.Thread(target=connection.run, daemon=True)
    worker.start()
    for _ in range(100):
        if len(stub.answers) == 2:
            break
        threading.Event().wait(0.05)
    connection.stop()
    assert stub.answers["c1"] == {"result": {"windows": [{"window": 7, "title": "Notepad"}]}}
    assert "does not know" in stub.answers["c2"]["error"]
    assert ("Listed the windows", False) in logged
    assert all(auth == "Bearer orkxc_good" for auth in stub.seen_auth if auth)


def test_a_credential_the_server_refuses_is_said_in_words():
    stub = Stub()
    with pytest.raises(ConnectionRefused, match="refused the credential"):
        Connection(stub.url, "orkx_bad", "1.0.0", FakeRunner()).hello()


def test_the_log_words_each_action():
    assert describe("click", {"ref": "e3"}) == "Clicked e3"
    assert describe("press", {"keys": "Ctrl+T"}) == "Pressed Ctrl+T"
    assert describe("open", {"target": "gedit"}) == "Opened gedit"
