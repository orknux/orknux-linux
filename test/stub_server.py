"""A stand-in Orknux: the client doors the real server has, plus /test/run for the driving script.

POST /test/run {"action", "arguments"} queues a command for the client and
answers with what the client posted back - so the driver talks to the client
exactly the way an agent's tool call does, through the long poll.
"""

import json
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CREDENTIAL = "orkxc_linux_test"
queue: list[dict] = []
answers: dict[str, dict] = {}
changed = threading.Condition()


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

    def _authorised(self):
        return self.headers.get("Authorization") == f"Bearer {CREDENTIAL}"

    def do_GET(self):
        if self.path.startswith("/api/client/compatibility"):
            return self._json(200, {"compatible": True})
        if not self._authorised():
            return self._json(401, {"error": "Unauthorized"})
        if self.path == "/api/desktop/hello":
            return self._json(200, {"user": "alice"})
        if self.path.startswith("/api/desktop/next"):
            assert "client=Linux" in self.path
            with changed:
                changed.wait_for(lambda: queue, timeout=5)
                if queue:
                    return self._json(200, queue.pop(0))
            self.send_response(204)
            self.end_headers()
            return None
        return self._json(404, {"error": "not here"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/api/clients/pair":
            if body.get("code", "").upper().replace("-", "") == "ABCDEF" and body.get("client") == "Linux":
                return self._json(200, {"credential": CREDENTIAL, "user": "alice"})
            return self._json(400, {"error": "That pairing code is not valid."})
        if self.path.startswith("/api/desktop/answers/"):
            if not self._authorised():
                return self._json(401, {})
            with changed:
                answers[self.path.rsplit("/", 1)[1]] = body
                changed.notify_all()
            self.send_response(204)
            self.end_headers()
            return None
        if self.path == "/test/run":
            command_id = uuid.uuid4().hex
            with changed:
                queue.append({"id": command_id, "action": body["action"], "arguments": body.get("arguments", {})})
                changed.notify_all()
                changed.wait_for(lambda: command_id in answers, timeout=60)
                answered = answers.pop(command_id, {"error": "the client never answered"})
            return self._json(200, answered)
        return self._json(404, {})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
