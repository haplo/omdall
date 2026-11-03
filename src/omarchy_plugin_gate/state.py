"""The state directory: markers, waivers, held candidates, evidence, the log.

The file formats are shared with earlier releases; keep them readable by both.
"""

import fcntl
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .output import Busy, warn


def now() -> str:
    """Local time like `date -Is`: 2026-10-28T22:15:03+01:00."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


# Everything str.splitlines() splits on, which is what read_lines uses, plus tab.
_LINE_BREAKS = str.maketrans(dict.fromkeys("\n\r\t\v\f\x1c\x1d\x1e\x85\u2028\u2029", " "))


def one_line(text: str) -> str:
    """`text` as one line of a state file, however read_lines splits it."""
    return text.translate(_LINE_BREAKS)


def write_atomic(path: Path, data: str | bytes) -> None:
    """Write via a temporary file and rename, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = data.encode("utf-8", "surrogateescape") if isinstance(data, str) else data
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_lines(path: Path) -> list[str]:
    """Lines of a text file, or [] when it is missing or unreadable."""
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


@dataclass(frozen=True, slots=True)
class Held:
    sha: str
    reasons: list[str]


@dataclass(frozen=True, slots=True)
class Waiver:
    date: str
    user: str
    reason: str


def parse_waiver(lines: list[str]) -> Waiver:
    """A waiver file: `WAIVED <date> <sha> by <user>`, then `reason: …`. A file
    that does not parse is still a waiver, with whatever could be read."""
    head = lines[0].split(" ", 4) if lines else []
    waived = len(head) >= 3 and head[0] == "WAIVED"
    date = head[1] if waived else ""
    user = head[4] if waived and len(head) == 5 and head[3] == "by" else ""
    reason = next((x.removeprefix("reason: ") for x in lines if x.startswith("reason: ")), "")
    return Waiver(date, user, reason)


@dataclass(frozen=True, slots=True)
class ReviewDir:
    """Evidence for one candidate commit."""

    path: Path

    @property
    def patch(self) -> Path:
        return self.path / "patch"

    @property
    def review_patch(self) -> Path:
        return self.path / "patch.review"

    @property
    def mech(self) -> Path:
        return self.path / "mech.txt"

    @property
    def findings(self) -> Path:
        return self.path / "findings.txt"

    @property
    def hints(self) -> Path:
        return self.path / "hints.txt"

    @property
    def review(self) -> Path:
        return self.path / "review.txt"

    @property
    def verdict(self) -> Path:
        return self.path / "verdict"

    @property
    def cleared(self) -> Path:
        return self.path / "cleared"

    def verdict_lines(self) -> list[str]:
        return read_lines(self.verdict)

    def cleared_count(self) -> int:
        return sum(1 for line in read_lines(self.cleared) if _is_finding_line(line))

    def findings_count(self) -> int:
        return sum(1 for line in read_lines(self.findings) if _is_finding_line(line))

    def reset(self) -> None:
        """A re-review of the same commit must not inherit a previous run's evidence."""
        self.path.mkdir(parents=True, exist_ok=True)
        for p in (self.cleared, self.hints, self.review, self.verdict, self.review_patch):
            p.unlink(missing_ok=True)


def _is_finding_line(line: str) -> bool:
    return len(line) > 1 and line[0] == "F" and line[1].isdigit()


class State:
    def __init__(self, root: Path) -> None:
        self.root = root

    def plugin_dir(self, name: str) -> Path:
        return self.root / name

    @property
    def lock_file(self) -> Path:
        return self.root / "gate.lock"

    @contextmanager
    def lock(self, *, wait: bool = True) -> Generator[None]:
        """One run at a time per state directory, so two runs never write the
        same evidence, held file or ref. Released when the process exits.
        Without `wait`, raises Busy when another run has it."""
        self.root.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_file, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if not wait:
                    raise Busy("another omarchy-plugin-gate run is in progress") from None
                warn("waiting for another run to finish…")
                fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def is_busy(self) -> bool:
        """Whether another run holds the lock right now. A hint for display only:
        the answer can be stale as soon as it is returned. The probe takes a
        shared lock for an instant, so probes never make each other busy."""
        try:
            fd = os.open(self.lock_file, os.O_RDONLY | os.O_CLOEXEC)
        except OSError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            os.close(fd)
        return False

    # -- approvals

    def marker(self, name: str, sha: str) -> Path:
        return self.plugin_dir(name) / "reviewed" / sha

    def waiver(self, name: str, sha: str) -> Path:
        return self.plugin_dir(name) / "waived" / sha

    def has_marker(self, name: str, sha: str) -> bool:
        return self.marker(name, sha).is_file()

    def has_waiver(self, name: str, sha: str) -> bool:
        return self.waiver(name, sha).is_file()

    def has_approval(self, name: str, sha: str) -> bool:
        return self.has_marker(name, sha) or self.has_waiver(name, sha)

    def set_marker(self, name: str, sha: str, note: str) -> None:
        write_atomic(self.marker(name, sha), f"APPROVED {now()} {sha} {one_line(note)}\n")
        self.held_file(name).unlink(missing_ok=True)

    def set_waiver(
        self,
        name: str,
        sha: str,
        *,
        user: str,
        reason: str,
        base: str,
        patch_blob: str,
        evidence_blob: str = "",
    ) -> None:
        """A waiver is a human decision, not a review result. It lives apart from
        reviewed/ so status can say a person overrode the model, and a later
        re-review cannot erase the record.

        `patch_blob` is the diff from `base` that the approval let through;
        `evidence_blob`, when set, the different patch the recorded review saw."""
        lines = [f"WAIVED {now()} {sha} by {one_line(user)}", f"reason: {one_line(reason)}"]
        if base:
            lines.append(f"base: {base}")
        if patch_blob:
            lines.append(f"patch-blob: {patch_blob}")
        if evidence_blob:
            lines.append(f"evidence-blob: {evidence_blob}")
        write_atomic(self.waiver(name, sha), "\n".join(lines) + "\n")
        held = self.held(name)
        if held and held.sha == sha:
            self.held_file(name).unlink(missing_ok=True)

    def waiver_reason(self, name: str, sha: str) -> str:
        record = self.waiver_record(name, sha)
        return record.reason if record else ""

    def waiver_record(self, name: str, sha: str) -> Waiver | None:
        if not self.has_waiver(name, sha):
            return None
        return parse_waiver(read_lines(self.waiver(name, sha)))

    def approved_shas(self, name: str) -> list[str]:
        """Every commit with a review marker or a waiver."""
        found: set[str] = set()
        for sub in ("reviewed", "waived"):
            with suppress(OSError):
                found.update(p.name for p in (self.plugin_dir(name) / sub).iterdir() if p.is_file())
        return sorted(found)

    # -- held candidates

    def held_file(self, name: str) -> Path:
        return self.plugin_dir(name) / "held"

    def held(self, name: str) -> Held | None:
        lines = read_lines(self.held_file(name))
        if not lines or not lines[0]:
            return None
        return Held(lines[0], lines[1:])

    def record_held(self, name: str, sha: str, reason: str | None = None) -> None:
        if reason is None:
            reason = "\n".join(self.review_dir(name, sha).verdict_lines()[1:6])
        write_atomic(self.held_file(name), f"{sha}\n{reason}\n")

    # -- evidence

    def review_dir(self, name: str, sha: str) -> ReviewDir:
        return ReviewDir(self.plugin_dir(name) / "reviews" / sha[:12])

    def review_dirs(self, name: str) -> list[ReviewDir]:
        """Every candidate's evidence, newest first."""
        try:
            dirs = [p for p in (self.plugin_dir(name) / "reviews").iterdir() if p.is_dir()]
        except OSError:
            return []
        dirs.sort(key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
        return [ReviewDir(p) for p in dirs]

    def latest_review_dir(self, name: str) -> ReviewDir | None:
        dirs = self.review_dirs(name)
        return dirs[0] if dirs else None

    # -- log and notification id

    def log_event(self, name: str, message: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "gate.log").open("a", encoding="utf-8", errors="replace") as f:
            f.write(f"{now()}\t{name} {one_line(message)}\n")

    @property
    def notify_id_file(self) -> Path:
        return self.root / "notify.id"

    def notify_id(self) -> int:
        lines = read_lines(self.notify_id_file)
        return int(lines[0]) if lines and lines[0].isascii() and lines[0].isdigit() else 0
