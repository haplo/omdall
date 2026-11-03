"""reviews: the evidence recorded for each candidate, newest first."""

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .. import mechanics
from ..context import Context
from ..git import Repo
from ..output import emit_json, indented, info, printable, say
from ..plugins import selected_names
from ..state import ReviewDir, read_lines

_SHORT_SHA = re.compile(r"[0-9a-f]{7,64}")

# Evidence files a review directory may hold, by the name --json gives them.
EVIDENCE = ("patch", "review_patch", "mech", "findings", "hints", "review", "verdict", "cleared")


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    short: str
    sha: str | None
    subject: str
    author: str
    date: str
    verdict: str
    passed: bool
    reasons: list[str]
    hard: list[str]
    findings: int
    cleared: int
    approval: str | None
    dir: str
    files: dict[str, str]


def full_sha(short: str, known: list[str], clone: Repo) -> str | None:
    """The commit a review directory (named by a short sha) belongs to."""
    if not _SHORT_SHA.fullmatch(short):
        return None
    match = [sha for sha in known if sha.startswith(short)]
    if len(match) == 1:
        return match[0]
    return clone.commit(short)


def _mtime(path: Path) -> str:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return ""
    return datetime.fromtimestamp(stamp).astimezone().isoformat(timespec="seconds")


def review_record(
    ctx: Context, name: str, clone: Repo, rd: ReviewDir, known: list[str]
) -> ReviewRecord:
    sha = full_sha(rd.path.name, known, clone)
    commit = clone.commit_info(sha) if sha else None
    verdict = rd.verdict_lines()
    mech = read_lines(rd.mech)
    approval = None
    if sha and ctx.state.has_marker(name, sha):
        approval = "reviewed"
    elif sha and ctx.state.has_waiver(name, sha):
        approval = "waived"
    files = {
        key: str(path)
        for key in EVIDENCE
        if (path := getattr(rd, key)).is_file()
    }  # fmt: skip
    return ReviewRecord(
        short=rd.path.name,
        sha=sha,
        subject=printable(commit.subject) if commit else "",
        author=printable(commit.author) if commit else "",
        date=_mtime(rd.verdict if rd.verdict.is_file() else rd.path),
        verdict=printable(verdict[0]) if verdict else "",
        passed=bool(verdict) and verdict[0].startswith("REVIEW PASS"),
        reasons=[printable(line) for line in verdict[1:]],
        hard=[] if not mech or mechanics.PASS_LINE in mech else [printable(x) for x in mech],
        findings=rd.findings_count(),
        cleared=rd.cleared_count(),
        approval=approval,
        dir=str(rd.path),
        files=files,
    )


def plugin_reviews(ctx: Context, name: str) -> list[ReviewRecord]:
    clone = ctx.clone(name)
    known = ctx.state.approved_shas(name)
    return [review_record(ctx, name, clone, rd, known) for rd in ctx.state.review_dirs(name)]


_APPROVAL_TEXT = {"reviewed": "approved by review", "waived": "approved by hand (waived)"}


def show(record: ReviewRecord) -> None:
    verdict = record.verdict or "no verdict recorded"
    approval = _APPROVAL_TEXT.get(record.approval or "", "")
    info(f"{record.short}  {verdict}  {record.date}{f'  {approval}' if approval else ''}")
    if record.subject:
        indented([f"{record.subject} ({record.author})"], 6)
    if record.hard:
        indented(["hard structural failures"], 6)
    if record.findings:
        indented([f"{record.findings} structural finding(s), {record.cleared} cleared"], 6)
    if not record.passed:
        indented(record.reasons[:5], 6)
    indented([f"evidence: {record.dir}"], 6)


def run(ctx: Context, want: str, *, as_json: bool = False) -> int:
    names = selected_names(ctx.cfg, want)
    entries = [(name, ctx.manifest_id(name), plugin_reviews(ctx, name)) for name in names]
    if as_json:
        emit_json(
            {
                "plugins": [
                    {"name": name, "id": pid or None, "reviews": [asdict(r) for r in records]}
                    for name, pid, records in entries
                ]
            }
        )
        return 0
    for name, pid, records in entries:
        say(f"{name}  ({pid})")
        if not records:
            info("no reviews yet")
        for record in records:
            show(record)
        say()
    return 0
