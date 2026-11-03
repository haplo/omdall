"""User-facing output. Diagnostics go to stderr with the command name."""

import json
import sys
from typing import Any

PREFIX = "omarchy-plugin-gate"

# Version of the --json output. Fields are only ever added; a removal or a
# change of meaning bumps it.
JSON_SCHEMA = 1

EXIT_BUSY = 75  # sysexits EX_TEMPFAIL: nothing ran, try again later


class GateError(Exception):
    """A user-facing failure: printed with the prefix, exit status `exit_code`.
    `code` names the kind of failure in --json output."""

    exit_code = 1
    code = "error"


class Busy(GateError):
    """Another run holds the state lock and this one was told not to wait."""

    exit_code = EXIT_BUSY
    code = "busy"


def emit_json(value: dict[str, Any]) -> None:
    print(json.dumps({"schema": JSON_SCHEMA, **value}, ensure_ascii=False, indent=2))


def say(msg: str = "") -> None:
    print(msg)


def info(msg: str) -> None:
    print(f"  {msg}")


def ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def bad(msg: str) -> None:
    print(f"  ✗ {msg}")


def warn(msg: str) -> None:
    sys.stdout.flush()
    print(f"{PREFIX}: {msg}", file=sys.stderr, flush=True)


def indented(lines: list[str], width: int = 14) -> None:
    pad = " " * width
    for line in lines:
        print(f"{pad}{printable(line)}")


def printable(text: str) -> str:
    """Escape control characters and undecodable bytes so one value stays on one line."""
    return "".join(
        c if c.isprintable() else c.encode("unicode_escape").decode("ascii") for c in text
    )


def safe_text(text: str) -> str:
    """printable() line by line, keeping newlines and tabs: for multi-line text
    such as a patch, shown to a person on a terminal."""
    return "\n".join(
        "\t".join(printable(part) for part in line.split("\t")) for line in text.split("\n")
    )
