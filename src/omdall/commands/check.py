"""check: fetch upstream, review new commits, stage approved ones. Never installs."""

from .. import proc
from ..config import APPROVED_REF
from ..context import Context
from ..hooks import ensure_hooks
from ..notify import CheckSummary, check_notification, notify
from ..output import info, printable, say, warn
from ..plugins import selected_names
from ..results import PluginResult, Report
from ..review import review
from . import advance_main, installed_sha


def _installed_lag(ctx: Context, name: str, approved: str, summary: CheckSummary) -> None:
    inst = installed_sha(ctx.installed_dir(name))
    if inst and inst != approved:
        summary.ready.append(name)


def result(
    ctx: Context,
    name: str,
    outcome: str,
    sha: str | None = None,
    message: str | None = None,
    cleared: int = 0,
) -> PluginResult:
    return PluginResult(name, ctx.manifest_id(name) or None, outcome, sha, message, cleared)


def held_message(ctx: Context, name: str, sha: str) -> str:
    """`REVIEW FAIL: <first reason>`, from the verdict on record."""
    lines = [printable(line) for line in ctx.state.review_dir(name, sha).verdict_lines()]
    if not lines:
        return "REVIEW FAIL"
    return f"{lines[0]}: {lines[1]}" if len(lines) > 1 and lines[1] else lines[0]


def check_one(
    ctx: Context,
    name: str,
    summary: CheckSummary,
    index: int | None = None,
    total: int | None = None,
) -> PluginResult:
    def error(message: str) -> PluginResult:
        summary.errors.append(name)
        warn(f"{name}: {message}")
        return result(ctx, name, "error", message=printable(message))

    ctx.progress("fetching", name, index, total)
    clone = ctx.clone(name)
    if not clone.is_repo():
        return error(f"{clone.path} is not a git repository")
    branch = clone.default_branch()
    if not branch:
        return error("cannot determine the default branch")
    fetched = clone.git("fetch", "--quiet", "origin", check=False)
    if not fetched.ok:
        return error(f"git fetch failed{f': {fetched.error}' if fetched.error else ''}")
    upstream = clone.upstream(branch)
    if not upstream:
        return error(f"no refs/remotes/origin/{branch} after fetch")

    approved = clone.rev(APPROVED_REF)
    base: str | None = None
    if not approved:
        head = clone.head()
        if not head:
            return error("the clone has no HEAD commit")
        say(f"{name}: no approved commit yet — bootstrapping review of {head}")
    elif approved == upstream:
        _installed_lag(ctx, name, approved, summary)
        return result(ctx, name, "up_to_date", approved)
    elif clone.is_ancestor(approved, upstream):
        head, base = upstream, approved
    else:
        summary.held.append(name)
        why = "upstream rewrote history; the approved commit is not an ancestor"
        ctx.state.record_held(name, upstream, why)
        return result(ctx, name, "held", upstream, why)

    if ctx.state.has_approval(name, head):
        clone.update_ref(APPROVED_REF, head, approved)
        advance_main(clone, head)
        _installed_lag(ctx, name, head, summary)
        waived = not ctx.state.has_marker(name, head)
        return result(ctx, name, "approved_waiver" if waived else "approved", head)

    say(f"{name}: reviewing {f'{base[:12]}..' if base else ''}{head[:12]}")
    if review(ctx, name, clone, base, head):
        ctx.state.set_marker(name, head, f"update from {base}" if base else "initial import")
        rd = ctx.state.review_dir(name, head)
        if rd.cleared.is_file():
            summary.cleared.append(name)
        clone.update_ref(APPROVED_REF, head, approved)
        advance_main(clone, head)
        ensure_hooks(ctx, name)
        _installed_lag(ctx, name, head, summary)
        return result(ctx, name, "approved", head, cleared=rd.cleared_count())
    summary.held.append(name)
    ctx.state.record_held(name, head)
    return result(ctx, name, "held", head, held_message(ctx, name, head))


def check_guarded(
    ctx: Context,
    name: str,
    summary: CheckSummary,
    index: int | None = None,
    total: int | None = None,
) -> PluginResult:
    """check_one, with a git or file error turned into an `error` result."""
    try:
        return check_one(ctx, name, summary, index, total)
    except (proc.CommandError, OSError) as e:
        summary.errors.append(name)
        warn(f"{name}: {e}")
        return result(ctx, name, "error", message=printable(str(e)))


def print_summary(summary: CheckSummary) -> None:
    ready, held, errors = summary.ready, summary.held, summary.errors
    say()
    say(f"ready to install: {len(ready)}   held back: {len(held)}   errors: {len(errors)}")
    if ready:
        info(" ".join(ready))
    if held:
        info(f"held: {' '.join(held)}")
    if errors:
        info(f"errors: {' '.join(errors)}")
    if summary.cleared:
        info(
            f"structural findings cleared by the reviewer: {' '.join(summary.cleared)} (see status)"
        )


def run(ctx: Context, want: str) -> Report:
    ctx.state.root.mkdir(parents=True, exist_ok=True)
    names = selected_names(ctx.cfg, want)
    summary = CheckSummary()
    if not names:
        say(f"No plugins under {ctx.cfg.root}.")
        return Report("check", 0, [], summary)

    results = [check_guarded(ctx, name, summary, i, len(names)) for i, name in enumerate(names, 1)]
    print_summary(summary)
    if message := check_notification(summary, ctx.cfg.notify_policy):
        notify(ctx, *message)
    return Report("check", 1 if summary.errors else 0, results, summary)
