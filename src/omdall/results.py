"""What an action command did: the records behind its --json output.

The text output of `check`, `update`, `add`, `adopt` and `doctor` is printed as
the work happens; each command also builds one of these records for the same
outcome, so the two cannot disagree.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

from .notify import CheckSummary

# Outcomes per plugin. Closed sets, documented in docs/scripting.md.
REVIEW_OUTCOMES = ("up_to_date", "approved", "approved_waiver", "held", "error")
ADD_OUTCOMES = (*REVIEW_OUTCOMES, "installed", "installed_disabled")
ADOPT_OUTCOMES = ("adopted", "error")
UPDATE_OUTCOMES = (
    "installed",
    "up_to_date",
    "blocked_dirty",
    "not_installed",
    "rolled_back",
    "error",
)


@dataclass(frozen=True, slots=True)
class PluginResult:
    """One plugin's outcome in a `check`, `update`, `add` or `adopt` run.

    `review` is set by `adopt` only: the outcome of the review that followed
    the adoption. `dirty` is set with `blocked_dirty`."""

    name: str
    id: str | None
    outcome: str
    sha: str | None = None
    message: str | None = None
    cleared: int = 0
    dirty: list[str] = field(default_factory=list)
    review: str | None = None


@dataclass(frozen=True, slots=True)
class DoctorResult:
    """One problem `doctor` found. `ok` is whether it is fine now, which only
    happens when `--fix` fixed it."""

    name: str | None
    check: str
    ok: bool
    message: str
    fixed: bool = False


@dataclass(frozen=True, slots=True)
class Report:
    command: str
    exit: int
    results: list[PluginResult] | list[DoctorResult]
    summary: CheckSummary | None = None

    def json(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "ok": self.exit == 0,
            "results": [asdict(r) for r in self.results],
            "summary": asdict(self.summary) if self.summary else None,
        }
