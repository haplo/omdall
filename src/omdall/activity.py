"""activity.json: the change signal and live progress for front ends.

One file in the state directory, rewritten on every change of a locked run:
when it starts, when it moves to another phase, and when it ends. A front end
watches it and runs `status --json` again when `seq` changes.

This is display data. Nothing in the gate reads it to decide anything, and a
failure to write it never fails a run.
"""

import json
import os
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .output import JSON_SCHEMA, printable
from .state import now, write_atomic

if TYPE_CHECKING:
    from .notify import CheckSummary

FILE_NAME = "activity.json"

# What a run is doing. A closed set, documented in docs/scripting.md.
PHASES = ("fetching", "checking", "reviewing", "installing", "validating", "adopting", "doctor")

# Commands that review, and so count as the last check.
CHECK_COMMANDS = frozenset({"check", "add", "adopt"})


@dataclass(frozen=True, slots=True)
class Running:
    command: str
    pid: int
    started: str
    plugin: str | None = None
    phase: str | None = None
    index: int | None = None
    total: int | None = None
    phase_started: str | None = None
    timeout: int | None = None


def parse(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _seq(data: dict[str, Any] | None) -> int:
    value = data.get("seq") if data else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


class Activity:
    """The activity file of one state directory, and the run this process is
    reporting, if any."""

    def __init__(self, state_root: Path) -> None:
        self.path = state_root / FILE_NAME
        self.running: Running | None = None

    def read(self) -> dict[str, Any] | None:
        """The file's contents, or None when it is missing or unreadable."""
        try:
            return parse(self.path.read_text(encoding="utf-8"))
        except OSError, UnicodeDecodeError:
            return None

    def _write(self, **fields: Any) -> None:
        data = self.read() or {}
        data.setdefault("last_run", None)
        data.setdefault("last_check", None)
        data.update(fields)
        data.update(schema=JSON_SCHEMA, seq=_seq(data) + 1, updated=now())
        if "running" not in data:
            data["running"] = None
        with suppress(OSError):
            write_atomic(self.path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    def _write_running(self) -> None:
        self._write(running=asdict(self.running) if self.running else None)

    def start(self, command: str) -> None:
        """A locked run begins. Call only while holding the state lock."""
        self.running = Running(command=command, pid=os.getpid(), started=now())
        self._write_running()

    def progress(
        self,
        phase: str,
        plugin: str | None = None,
        index: int | None = None,
        total: int | None = None,
        timeout: int | None = None,
    ) -> None:
        """The running command moved on. A no-op outside a locked run. Naming
        the same plugin again without an index keeps its index and total."""
        r = self.running
        if r is None:
            return
        if phase not in PHASES:
            raise ValueError(f"unknown activity phase: {phase}")
        shown = printable(plugin) if plugin is not None else None
        if shown is not None and shown == r.plugin and index is None:
            index, total = r.index, r.total
        if timeout is not None and phase != "reviewing":
            timeout = None
        if (r.phase, r.plugin, r.index, r.total, r.timeout) == (
            phase,
            shown,
            index,
            total,
            timeout,
        ):
            return
        self.running = replace(
            r,
            phase=phase,
            plugin=shown,
            index=index,
            total=total,
            phase_started=now(),
            timeout=timeout,
        )
        self._write_running()

    def finish(self, exit_code: int, summary: CheckSummary | None = None) -> None:
        """The run ended, however it ended: clear `running`, record the result."""
        r = self.running
        if r is None:
            return
        self.running = None
        finished = now()
        result = asdict(summary) if summary is not None else None
        fields: dict[str, Any] = {
            "running": None,
            "last_run": {
                "command": r.command,
                "started": r.started,
                "finished": finished,
                "exit": exit_code,
                "summary": result,
            },
        }
        if r.command in CHECK_COMMANDS:
            fields["last_check"] = {"finished": finished, "exit": exit_code, "summary": result}
        self._write(**fields)


def for_status(data: dict[str, Any] | None, busy: bool) -> dict[str, Any] | None:
    """The file as status --json shows it. The lock is the truth: `running` is
    left only while some run holds it, so a crashed run's leftover is hidden."""
    if data is None:
        return None
    return {**data, "running": data.get("running") if busy else None}
