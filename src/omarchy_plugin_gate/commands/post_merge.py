"""_post-merge: the tripwire's entry point, run by the hook after a merge."""

from pathlib import Path

from ..context import Context
from ..git import Repo
from ..hooks import is_upstream_commit
from ..notify import notify
from ..output import printable, warn
from ..plugins import approved_manifest_id, plugin_names, same_path
from ..review import review
from . import disable_plugin


def run(ctx: Context, name: str, directory: str) -> int:
    """`name` comes from the hook, written by the gate. The merged files are
    never asked which plugin they belong to: a commit could change the answer."""
    if name not in plugin_names(ctx.cfg):
        warn(f"tripwire: no plugin named '{printable(name)}' under {ctx.cfg.root}")
        return 0
    if not directory or not Path(directory).is_dir():
        return 0
    target = Path(directory)
    repo = Repo(target)
    if not repo.is_repo():
        return 0

    clone = ctx.clone(name)
    plugin_id = approved_manifest_id(clone)
    installed = bool(plugin_id) and same_path(target, ctx.cfg.installed_root / plugin_id)
    if not installed and not same_path(target, ctx.clone_dir(name)):
        ctx.state.log_event(name, f"hook: {target} is neither the clone nor the installed copy")
        return 0

    new = repo.head()
    old = repo.rev("ORIG_HEAD")
    if not new or not old or new == old:
        return 0
    if ctx.state.has_approval(name, new) or not is_upstream_commit(clone, new):
        return 0

    ctx.state.log_event(name, f"hook: reviewing out-of-band merge {old}..{new} in {target}")
    if review(ctx, name, clone, old, new):
        ctx.state.set_marker(name, new, "hook review")
        return 0

    # --keep, never --hard: uncommitted work the merge did not touch must survive.
    rolled_back = repo.ok("reset", "--keep", "--quiet", old, no_attributes=True)
    if installed:
        disable_plugin(plugin_id)
    if not rolled_back:
        problem = f"could not roll back {new} without discarding local changes"
        warn(f"tripwire: {problem} in {target}")
        ctx.state.log_event(name, f"hook: {problem}")
        notify(
            ctx,
            f"{name}: rollback failed",
            f"The review of {new} failed, but it could not be rolled back without "
            f"discarding local changes in {target}"
            f"{', so the plugin was disabled' if installed else ''}. Look at it by hand.",
        )
        return 1
    ctx.state.log_event(name, f"hook: rolled back {new}")
    notify(
        ctx,
        f"{name}: update rolled back",
        f"The review failed, so {new} was reverted and the plugin disabled.",
    )
    return 1
