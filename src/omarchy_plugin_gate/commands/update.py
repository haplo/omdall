"""update: apply approved commits to the installed copies and rescan."""

from .. import proc
from ..config import APPROVED_REF
from ..context import Context
from ..git import Repo
from ..hooks import ensure_hooks
from ..install import install_new
from ..notify import notify, notify_close
from ..output import info, say, warn
from ..plugins import approved_manifest_id, selected_names
from . import disable_plugin, installed_sha, path_list


def _detail(result: proc.Result) -> str:
    return f": {result.error}" if result.error else ""


def _roll_back(ctx: Context, name: str, installed: Repo, before: str | None) -> None:
    if before:
        installed.ok("reset", "--hard", "--quiet", before, no_attributes=True)
    disable_plugin(approved_manifest_id(ctx.clone(name)))


def update_one(ctx: Context, name: str, *, first_install: bool) -> bool:
    """True when a new commit was installed. `first_install` lets a plugin with
    no installed copy be installed; only for plugins named on the command line,
    so one removed on purpose does not come back."""
    clone = ctx.clone(name)
    approved = clone.rev(APPROVED_REF)
    if not approved:
        warn(f"{name}: nothing approved yet (run: omarchy-plugin-gate check -p {name})")
        return False
    if not ctx.state.has_approval(name, approved):
        warn(f"{name}: approved commit {approved} has no review or waiver record; refusing")
        return False
    idir = ctx.installed_dir(name)
    if idir is None or not idir.is_dir():
        if not first_install:
            info(
                f"{name}: approved {approved[:12]}, not installed "
                f"(install with: omarchy-plugin-gate update -p {name})"
            )
            return False
        say(f"{name}: installing {approved[:12]} (first install)")
        return install_new(ctx, name, approved, enable_after=True)
    before = installed_sha(idir)
    if before == approved:
        info(f"{name}: up to date ({approved[:12]})")
        return False

    installed = Repo(idir)
    # Edited or untracked files survive a fast-forward and were never reviewed.
    dirty = installed.dirty_paths()
    if dirty:
        warn(f"{name}: the installed copy has local changes ({path_list(dirty)}); not updating")
        return False
    fetched = installed.git("fetch", "--quiet", "origin", APPROVED_REF, check=False)
    if not fetched.ok:
        warn(f"{name}: could not fetch gate-approved from the clone{_detail(fetched)}")
        return False
    new = installed.rev("FETCH_HEAD")
    if new is None or new != approved:
        warn(
            f"{name}: origin gate-approved ({new}) does not match the approved commit "
            f"({approved}); refusing"
        )
        return False

    say(f"{name}: installing {approved[:12]}")
    # No attributes: a filter driver configured on this machine must not
    # rewrite the reviewed files on their way to disk.
    merged = installed.git("merge", "--ff-only", "--quiet", new, check=False, no_attributes=True)
    if not merged.ok:
        warn(f"{name}: cannot fast-forward (local changes in {idir}){_detail(merged)}")
        return False
    if installed.head() != new:
        warn(f"{name}: merge landed on the wrong commit; rolling back")
        _roll_back(ctx, name, installed, before)
        notify(
            ctx,
            f"{name}: update rolled back",
            "The installed copy did not match the approved commit.",
        )
        return False

    if not proc.run_quiet(["omarchy", "plugin", "validate", str(idir)]):
        warn(f"{name}: manifest validation failed after merge; rolling back")
        _roll_back(ctx, name, installed, before)
        return False

    ctx.state.log_event(name, f"installed {new}")
    ensure_hooks(ctx, name)
    return True


def run(ctx: Context, want: str) -> int:
    ctx.state.root.mkdir(parents=True, exist_ok=True)
    applied = 0
    for name in selected_names(ctx.cfg, want):
        try:
            applied += update_one(ctx, name, first_install=bool(want))
        except (proc.CommandError, OSError) as e:
            warn(f"{name}: {e}")

    if applied:
        if not proc.run_quiet(["omarchy-shell", "shell", "rescanPlugins"]):
            warn("could not ask the shell to rescan plugins")
        notify_close(ctx)
        say(f"Applied {applied} update(s).")
    else:
        say("Nothing to apply.")
    return 0
