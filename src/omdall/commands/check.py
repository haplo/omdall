"""check: fetch upstream, review new commits, stage approved ones. Never installs."""

from .. import proc
from ..config import APPROVED_REF
from ..context import Context
from ..hooks import ensure_hooks
from ..notify import CheckSummary, check_notification, notify
from ..output import info, say, warn
from ..plugins import selected_names
from ..review import review
from . import advance_main, installed_sha


def _installed_lag(ctx: Context, name: str, approved: str, summary: CheckSummary) -> None:
    inst = installed_sha(ctx.installed_dir(name))
    if inst and inst != approved:
        summary.ready.append(name)


def check_one(ctx: Context, name: str, summary: CheckSummary) -> None:
    clone = ctx.clone(name)
    if not clone.is_repo():
        summary.errors.append(name)
        warn(f"{name}: {clone.path} is not a git repository")
        return
    branch = clone.default_branch()
    if not branch:
        summary.errors.append(name)
        warn(f"{name}: cannot determine the default branch")
        return
    fetched = clone.git("fetch", "--quiet", "origin", check=False)
    if not fetched.ok:
        summary.errors.append(name)
        warn(f"{name}: git fetch failed{f': {fetched.error}' if fetched.error else ''}")
        return
    upstream = clone.upstream(branch)
    if not upstream:
        summary.errors.append(name)
        warn(f"{name}: no refs/remotes/origin/{branch} after fetch")
        return

    approved = clone.rev(APPROVED_REF)
    base: str | None = None
    if not approved:
        head = clone.head()
        if not head:
            summary.errors.append(name)
            warn(f"{name}: the clone has no HEAD commit")
            return
        say(f"{name}: no approved commit yet — bootstrapping review of {head}")
    elif approved == upstream:
        _installed_lag(ctx, name, approved, summary)
        return
    elif clone.is_ancestor(approved, upstream):
        head, base = upstream, approved
    else:
        summary.held.append(name)
        ctx.state.record_held(
            name, upstream, "upstream rewrote history; the approved commit is not an ancestor"
        )
        return

    if ctx.state.has_approval(name, head):
        clone.update_ref(APPROVED_REF, head, approved)
        advance_main(clone, head)
        _installed_lag(ctx, name, head, summary)
        return

    say(f"{name}: reviewing {f'{base[:12]}..' if base else ''}{head[:12]}")
    if review(ctx, name, clone, base, head):
        ctx.state.set_marker(name, head, f"update from {base}" if base else "initial import")
        if ctx.state.review_dir(name, head).cleared.is_file():
            summary.cleared.append(name)
        clone.update_ref(APPROVED_REF, head, approved)
        advance_main(clone, head)
        ensure_hooks(ctx, name)
        _installed_lag(ctx, name, head, summary)
    else:
        summary.held.append(name)
        ctx.state.record_held(name, head)


def run(ctx: Context, want: str) -> int:
    ctx.state.root.mkdir(parents=True, exist_ok=True)
    names = selected_names(ctx.cfg, want)
    if not names:
        say(f"No plugins under {ctx.cfg.root}.")
        return 0

    summary = CheckSummary()
    for name in names:
        try:
            check_one(ctx, name, summary)
        except (proc.CommandError, OSError) as e:
            summary.errors.append(name)
            warn(f"{name}: {e}")

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

    if message := check_notification(summary, ctx.cfg.notify_policy):
        notify(ctx, *message)
    return 1 if errors else 0
