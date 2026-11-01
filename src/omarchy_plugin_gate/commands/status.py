"""status: what is installed, approved, upstream, and held."""

from ..config import APPROVED_REF
from ..context import Context
from ..git import Repo
from ..output import indented, info, printable, say
from ..plugins import selected_names
from . import installed_sha, path_list


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


def show_one(ctx: Context, name: str) -> None:
    clone = ctx.clone(name)
    plugin_id = ctx.manifest_id(name)
    idir = ctx.installed_dir(name)
    approved = clone.rev(APPROVED_REF) or ""
    branch = clone.default_branch()
    upstream = clone.upstream(branch or "main") or ""
    inst = installed_sha(idir) or ""
    held = ctx.state.held(name)
    state = plugin_state(
        approved or None, inst or None, bool(idir and idir.is_dir()), held.sha if held else None
    )

    say(f"{name}  ({plugin_id})")
    info(f"clone     {clone.path}")
    info(f"approved  {approved[:12]}{'  (gate-approved)' if approved else ''}")
    info(f"installed {inst[:12]}{f'  ({idir})' if inst else ''}")
    info(
        f"upstream  {upstream[:12]}{f'  (origin/{branch}, as of the last check)' if branch else ''}"
    )
    info(f"state     {state}")
    if inst and idir:
        dirty = Repo(idir).dirty_paths()
        if dirty:
            info(f"local     modified: {path_list(dirty)}")
        if not ctx.state.has_approval(name, inst):
            info("warning   installed commit never reviewed")
    if approved and ctx.state.has_waiver(name, approved):
        reason = ctx.state.waiver_reason(name, approved)
        info(f"approval  waived by hand{f' — {reason}' if reason else ''}")
    if approved:
        rd = ctx.state.review_dir(name, approved)
        if rd.cleared.is_file():
            info(f"findings  {rd.cleared_count()} cleared by the reviewer — {rd.cleared}")
    if state == "held back":
        info(f"next      omarchy-plugin-gate approve -p {name}   (or check -p {name} to retry)")
    elif state == "approved, not installed":
        info(f"next      omarchy-plugin-gate update -p {name}")

    latest = ctx.state.latest_review_dir(name)
    verdict = latest.verdict_lines() if latest else []
    if verdict and verdict[0].startswith("REVIEW FAIL"):
        info(f"last review: {printable(verdict[0])}")
        indented(verdict[1:6])
        info(f"patch: {latest.patch if latest else ''}")
    elif verdict and verdict[0]:
        info(f"last review: {printable(verdict[0])}")
    say()


def run(ctx: Context, want: str) -> int:
    for name in selected_names(ctx.cfg, want):
        show_one(ctx, name)
    return 0
