"""status: what is installed, approved, upstream, and held."""

from dataclasses import asdict, dataclass
from pathlib import Path

from .. import __version__
from ..config import APPROVED_REF
from ..context import Context
from ..git import Repo
from ..output import emit_json, indented, info, printable, say
from ..plugins import selected_names
from ..state import Waiver
from . import installed_sha, path_list
from .reviews import ReviewRecord, review_record


def plugin_state(
    approved: str | None, installed: str | None, installed_exists: bool, held: str | None
) -> str:
    if held and held != approved:
        return "held back"
    if not approved:
        return "not reviewed yet"
    if installed == approved:
        return "installed"
    if installed or installed_exists:
        return "ready to install"
    return "approved, not installed"


# The command that moves each state along, for a caller that offers one.
NEXT = {
    "held back": "approve",
    "not reviewed yet": "check",
    "ready to install": "update",
    "approved, not installed": "update",
}


@dataclass(frozen=True, slots=True)
class HeldRecord:
    sha: str
    reasons: list[str]


@dataclass(frozen=True, slots=True)
class PluginRecord:
    name: str
    id: str | None
    clone: str
    installed_dir: str | None
    branch: str | None
    approved: str | None
    installed: str | None
    upstream: str | None
    state: str
    next: str | None
    dirty: list[str]
    never_reviewed: bool
    waiver: Waiver | None
    cleared: int
    cleared_file: str | None
    held: HeldRecord | None
    latest_review: ReviewRecord | None


def plugin_record(ctx: Context, name: str) -> PluginRecord:
    clone = ctx.clone(name)
    plugin_id = ctx.manifest_id(name)
    idir = ctx.installed_dir(name)
    approved = clone.rev(APPROVED_REF)
    branch = clone.default_branch()
    upstream = clone.upstream(branch or "main")
    inst = installed_sha(idir)
    held = ctx.state.held(name)
    state = plugin_state(approved, inst, bool(idir and idir.is_dir()), held.sha if held else None)

    dirty: list[str] = []
    never_reviewed = False
    if inst and idir:
        dirty = [printable(p) for p in Repo(idir).dirty_paths()]
        never_reviewed = not ctx.state.has_approval(name, inst)
    waiver = ctx.state.waiver_record(name, approved) if approved else None
    cleared_rd = ctx.state.review_dir(name, approved) if approved else None
    has_cleared = bool(cleared_rd and cleared_rd.cleared.is_file())
    latest = ctx.state.latest_review_dir(name)
    return PluginRecord(
        name=name,
        id=plugin_id or None,
        clone=str(clone.path),
        installed_dir=str(idir) if idir else None,
        branch=branch,
        approved=approved,
        installed=inst,
        upstream=upstream,
        state=state,
        next=NEXT.get(state),
        dirty=dirty,
        never_reviewed=never_reviewed,
        waiver=waiver,
        cleared=cleared_rd.cleared_count() if cleared_rd and has_cleared else 0,
        cleared_file=str(cleared_rd.cleared) if cleared_rd and has_cleared else None,
        held=HeldRecord(printable(held.sha), [printable(r) for r in held.reasons])
        if held
        else None,
        latest_review=review_record(ctx, name, clone, latest, ctx.state.approved_shas(name))
        if latest
        else None,
    )


def show(r: PluginRecord) -> None:
    approved, inst, upstream = r.approved or "", r.installed or "", r.upstream or ""
    say(f"{r.name}  ({r.id or ''})")
    info(f"clone     {r.clone}")
    info(f"approved  {approved[:12]}{'  (gate-approved)' if approved else ''}")
    info(f"installed {inst[:12]}{f'  ({r.installed_dir})' if inst else ''}")
    info(
        f"upstream  {upstream[:12]}"
        f"{f'  (origin/{r.branch}, as of the last check)' if r.branch else ''}"
    )
    info(f"state     {r.state}")
    if r.dirty:
        info(f"local     modified: {path_list(r.dirty)}")
    if r.never_reviewed:
        info("warning   installed commit never reviewed")
    if r.waiver:
        reason = r.waiver.reason
        info(f"approval  waived by hand{f' — {reason}' if reason else ''}")
    if r.cleared_file:
        info(f"findings  {r.cleared} cleared by the reviewer — {r.cleared_file}")
    if r.state == "held back":
        info(f"next      omarchy-plugin-gate approve -p {r.name}   (or check -p {r.name} to retry)")
    elif r.state == "approved, not installed":
        info(f"next      omarchy-plugin-gate update -p {r.name}")

    latest = r.latest_review
    if latest and latest.verdict.startswith("REVIEW FAIL"):
        info(f"last review: {latest.verdict}")
        indented(latest.reasons[:5])
        info(f"patch: {Path(latest.dir) / 'patch'}")
    elif latest and latest.verdict:
        info(f"last review: {latest.verdict}")
    say()


def run(ctx: Context, want: str, *, as_json: bool = False) -> int:
    busy = ctx.state.is_busy()
    records = [plugin_record(ctx, name) for name in selected_names(ctx.cfg, want)]
    if as_json:
        emit_json(
            {
                "version": __version__,
                "root": str(ctx.cfg.root),
                "state": str(ctx.state.root),
                "busy": busy,
                "plugins": [asdict(r) for r in records],
            }
        )
        return 0
    if busy:
        say("another omarchy-plugin-gate run is in progress; this may change when it finishes")
        say()
    for r in records:
        show(r)
    return 0
