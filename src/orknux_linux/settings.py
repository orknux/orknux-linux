"""What is remembered between starts: the server, whether to reconnect, and the credential.

The server and the reconnect mark are in ~/.config/orknux/desktop.json. The
credential is kept in the desktop's keyring through the Secret Service where
there is one, and otherwise in a file only this account can read - never in the
JSON beside the server address.
"""

import json
import os
from pathlib import Path

SERVICE = "orknux-linux"


def _folder() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "orknux"


class Settings:
    def __init__(self, server: str = "", reconnect: bool = False, portal_token: str = ""):
        self.server = server
        # The RemoteDesktop portal's restore token: the person's yes to "allow remote interaction", kept so a
        # Wayland desktop does not ask again on every start. Not a credential, but it stands for one, so the
        # file it is in is readable by this account only.
        self.portal_token = portal_token
        # Set by a connection that worked, cleared by the person disconnecting or pressing Ctrl+Alt+Q,
        # so a restart picks up where it was and a deliberate stop stays one.
        self.reconnect = reconnect

    @classmethod
    def load(cls) -> "Settings":
        try:
            held = json.loads((_folder() / "desktop.json").read_text())
            return cls(str(held.get("server", "")), bool(held.get("reconnect", False)), str(held.get("portalToken", "")))
        except (OSError, ValueError):
            return cls()

    def save(self):
        folder = _folder()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "desktop.json"
        held = {"server": self.server, "reconnect": self.reconnect}
        if self.portal_token:
            held["portalToken"] = self.portal_token
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(json.dumps(held, indent=2))
        os.chmod(path, 0o600)

    # ---- the credential ----

    @staticmethod
    def _keyring():
        try:
            import keyring
            from keyring.backends import fail

            if isinstance(keyring.get_keyring(), fail.Keyring):
                return None
            return keyring
        except Exception:
            return None

    @property
    def token(self) -> str:
        ring = self._keyring()
        if ring is not None:
            try:
                return ring.get_password(SERVICE, "credential") or ""
            except Exception:
                pass
        try:
            return (_folder() / "credential").read_text().strip()
        except OSError:
            return ""

    @token.setter
    def token(self, value: str):
        ring = self._keyring()
        if ring is not None:
            try:
                ring.set_password(SERVICE, "credential", value)
                (_folder() / "credential").unlink(missing_ok=True)
                return
            except Exception:
                pass
        folder = _folder()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "credential"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(value)
        os.chmod(path, 0o600)
