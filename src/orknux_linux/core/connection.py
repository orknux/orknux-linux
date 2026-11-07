"""The door to the server, the same one Orknux for Windows uses: DeviceKind.DESKTOP.

Long-polls GET /api/desktop/next, runs each command it is handed, and posts the
result - or the refusal, in words - to /api/desktop/answers/{id}. Nothing listens
on this computer: the server is only ever answered.
"""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from .errors import ConnectionRefused, Refused

WAIT_SECONDS = 25
RETRY_SECONDS = 3


def describe(action: str, args: dict) -> str:
    """One line of the activity log for a command, the way the Windows app words it."""
    if action == "open":
        return f"Opened {args.get('target')}"
    if action == "click":
        return f"Clicked {args['ref']}" if args.get("ref") else f"Clicked at {args.get('x')}, {args.get('y')}"
    if action == "type":
        return f"Typed into {args['ref']}" if args.get("ref") else "Typed"
    return {
        "press": f"Pressed {args.get('keys')}",
        "snapshot": "Read a window",
        "screenshot": "Took a screenshot",
        "scroll": f"Scrolled {args.get('direction') or 'down'}",
        "focus": "Switched windows",
        "close": "Closed a window",
        "windows": "Listed the windows",
    }.get(action, action)


class Connection:
    """
    One connection to one server with one credential. The runner is anything with
    run(action, arguments) -> dict, raising Refused for what it will not do.
    """

    def __init__(self, server: str, token: str, version: str, runner,
                 log: Callable[[str, bool], None] = lambda line, failed: None,
                 state: Callable[[str], None] = lambda said: None,
                 busy: Callable[[bool], None] = lambda on: None):
        self.server = server.rstrip("/")
        self.token = token.strip()
        self.version = version
        self.runner = runner
        self.log = log
        self.state = state
        self.busy = busy
        self.stopped = threading.Event()

    # ---- HTTP ----

    def _request(self, method: str, path: str, body: dict | None = None, timeout: float = 30):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.server + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "User-Agent": f"OrknuxForLinux/{self.version}",
            **({"Content-Type": "application/json"} if data is not None else {}),
        })
        try:
            with urllib.request.urlopen(request, timeout=timeout) as answer:
                return answer.status, answer.read()
        except urllib.error.HTTPError as answered:
            return answered.code, answered.read()

    # ---- the conversation ----

    def hello(self) -> str:
        """Who the credential belongs to, after asking whether this server and client work together."""
        try:
            status, body = self._request("GET", "/api/client/compatibility?client=" + urllib.parse.quote(self.version))
            if status == 200:
                said = json.loads(body or b"{}")
                if said.get("compatible") is False:
                    raise ConnectionRefused(said.get("reason") or "This server and this client do not work together.")
            status, body = self._request("GET", "/api/desktop/hello")
        except (urllib.error.URLError, OSError) as failed:
            raise ConnectionRefused(f"The server could not be reached: {getattr(failed, 'reason', failed)}") from None
        if status == 401:
            raise ConnectionRefused("The server refused the credential. Make a new pairing link in Orknux: "
                                    "Preferences › Connected clients › Connect a client.")
        if status == 404:
            raise ConnectionRefused("This server has no desktop door. It is older than Orknux for Linux; update it.")
        if status != 200:
            raise ConnectionRefused(f"The server answered {status}. Is this the address of an Orknux server?")
        try:
            user = json.loads(body).get("user")
        except ValueError:
            user = None
        if not user:
            raise ConnectionRefused("The server did not say who the credential belongs to.")
        return user

    def run(self):
        """Polls until stopped, or until the server stops accepting the credential."""
        path = f"/api/desktop/next?wait={WAIT_SECONDS}&client=Linux&version={urllib.parse.quote(self.version)}"
        while not self.stopped.is_set():
            try:
                status, body = self._request("GET", path, timeout=WAIT_SECONDS + 20)
            except (urllib.error.URLError, OSError, TimeoutError):
                self.state("Reconnecting…")
                self.stopped.wait(RETRY_SECONDS)
                continue
            if self.stopped.is_set():
                return
            if status == 401:
                self.state("Disconnected: the server no longer accepts the credential.")
                return
            if status == 204:
                self.state("Connected")
                continue
            if status != 200:
                self.state("Reconnecting…")
                self.stopped.wait(RETRY_SECONDS)
                continue
            self.state("Connected")
            command = self._read(body)
            if command is not None:
                self._perform(*command)

    def stop(self):
        self.stopped.set()

    @staticmethod
    def _read(body: bytes):
        try:
            node = json.loads(body)
        except ValueError:
            return None
        if not isinstance(node, dict) or not node.get("id") or not node.get("action"):
            return None
        arguments = node.get("arguments") if isinstance(node.get("arguments"), dict) else {}
        return str(node["id"]), str(node["action"]), arguments

    def _perform(self, command_id: str, action: str, args: dict):
        self.busy(True)
        try:
            body = {"result": self.runner.run(action, args)}
            self.log(describe(action, args), False)
        except Refused as refused:
            body = {"error": str(refused)}
            self.log(f"{describe(action, args)} - {refused}", True)
        except Exception as failed:  # the computer could not: said, never swallowed
            body = {"error": f"The computer could not do that: {failed}"}
            self.log(f"{describe(action, args)} - {failed}", True)
        finally:
            self.busy(False)
        try:
            status, _ = self._request("POST", "/api/desktop/answers/" + urllib.parse.quote(command_id), body)
            if status == 410:
                self.log("The agent had stopped waiting for that answer.", True)
        except (urllib.error.URLError, OSError):
            if not self.stopped.is_set():
                self.log("The answer could not be sent back.", True)


def wait_for(condition: Callable[[], bool], seconds: float, step: float = 0.05) -> bool:
    """Polls condition until it holds or the time is up; whether it held."""
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if condition():
            return True
        time.sleep(step)
    return condition()
