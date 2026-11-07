"""Pairing: a link or a code from Orknux traded once for this computer's own credential.

The same shapes as the other clients: a code like K7P-4QX (any case, dash
optional), and a link <server>/pair/<code> that carries the server with it -
everything before the last /pair/ is the server, so one under a path prefix works.
"""

import json
import re
import socket
import urllib.error
import urllib.request

from .errors import ConnectionRefused

_CODE = r"[A-HJ-NP-Za-hj-np-z2-9]{3}-?[A-HJ-NP-Za-hj-np-z2-9]{3}"
CODE_SHAPE = re.compile(rf"^{_CODE}$")
LINK_SHAPE = re.compile(rf"^(https?://.+)/pair/({_CODE})/?$", re.IGNORECASE)


def is_code(typed: str) -> bool:
    return bool(CODE_SHAPE.match(typed.strip()))


def parse_link(text: str) -> tuple[str, str] | None:
    """The server and the code of a pairing link, or None when it is not one."""
    match = LINK_SHAPE.match(text.strip())
    if not match:
        return None
    server = match.group(1).rstrip("/")
    if not re.match(r"^https?://[^/\s]+", server, re.IGNORECASE):
        return None
    return server, match.group(2)


def trade(server: str, code: str, name: str | None = None, timeout: float = 30) -> str:
    """Trades a pairing code at the server for a credential, or says in words why not."""
    body = json.dumps({"code": code.strip(), "client": "Linux", "name": name or f"Linux on {socket.gethostname()}"}).encode()
    request = urllib.request.Request(server.rstrip("/") + "/api/clients/pair", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            said = json.loads(answer.read() or b"{}")
    except urllib.error.HTTPError as refused:
        try:
            said = json.loads(refused.read() or b"{}")
        except ValueError:
            said = {}
        raise ConnectionRefused(said.get("error") or f"The server answered {refused.code} to the pairing code. "
                                "Is this the address of an Orknux server?") from None
    except (urllib.error.URLError, OSError) as failed:
        raise ConnectionRefused(f"The server could not be reached: {getattr(failed, 'reason', failed)}") from None
    except ValueError:
        raise ConnectionRefused("The server did not answer the pairing code as Orknux does. "
                                "Is this the address of an Orknux server?") from None
    credential = said.get("credential")
    if not credential:
        raise ConnectionRefused(said.get("error") or "The server did not hand back a credential.")
    return credential


def resolve(first: str, second: str) -> tuple[str, str, bool]:
    """
    What was typed into the two fields, as server, secret and whether the secret
    is a code to trade: a pairing link in either field, or a server and a code,
    or a server and a token.
    """
    for field in (first, second):
        link = parse_link(field or "")
        if link:
            return link[0], link[1], True
    server = (first or "").strip().rstrip("/")
    secret = (second or "").strip()
    return server, secret, is_code(secret)
