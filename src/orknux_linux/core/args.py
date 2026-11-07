"""Reading a command's arguments the way Orknux for Windows does: lenient about numbers sent as text."""


def text(args: dict, name: str) -> str | None:
    value = args.get(name)
    return value if isinstance(value, str) and value != "" else None


def number(args: dict, name: str) -> int | None:
    value = args.get(name)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def flag(args: dict, name: str) -> bool:
    value = args.get(name)
    return value is True or (isinstance(value, str) and value.lower() == "true")
