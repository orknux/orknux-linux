class Refused(Exception):
    """An action that cannot be done, said in words the agent reads and acts on."""


class ConnectionRefused(Exception):
    """The server would not have this client: a wrong token, an old server, nobody there."""
