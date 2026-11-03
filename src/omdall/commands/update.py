"""update: apply approved commits to the installed copies and rescan."""

from .. import proc
from ..config import APPROVED_REF
from ..context import Context
from ..git import Repo
from ..hooks import ensure_hooks
from ..install import install_new
from ..notify import notify, notify_close
from ..output import info, printable, say, warn
from ..plugins import approved_manifest_id, selected_names
from ..results import PluginResult, Report
from . import disable_plugin, installed_sha, path_list


def _detail(result: proc.Result) -> str:
    return f": {result.error}" if result.error else ""


def _roll_back(ctx: Context, name: str, installed: Repo, before: str | None) -> bool:
    """Back to `before` and disabled. False when going back would have meant
    discarding local changes; the plugin is disabled either way."""
    rolled_back = not before or installed.ok(
        "reset", "--keep", "--quiet", before, no_attributes=True
    )
    disable_plugin(approved_manifest_id(ctx.clone(name)))
    if not rolled_back:
        problem = f"could not roll back to {before} without discarding local changes"
        warn(f"{name}: {problem} in {installed.path}; the plugin is disabled")
        ctx.state.log_event(name, f"update: {problem}")
        notify(
            ctx,
            f"{name}: rollback failed",
            f"The installed copy could not be rolled back without discarding local "
            f"changes in {installed.path}, so the plugin was disabled. Look at it by hand.",
        )
    return rolled_back


def update_one(ctx: Context, name: str, *, first_install: bool) -> PluginResult:
    """`installed` when a new commit was installed. `first_install` lets a plugin
    with no installed copy be installed; only for plugins named on the command
    line, so one removed on purpose does not come back."""
    plugin_id = ctx.manifest_id(name) or None

    def outcome(
        kind: str, sha: str | None, message: str | None = None, dirty: list[str] | None = None
    ) -> PluginResult:
        return PluginResult(name, plugin_id, kind, sha, message, dirty=dirty or [])

    def error(message: str, sha: str | None = None) -> PluginResult:
        warn(f"{name}: {message}")
        return outcome("error", sha, printable(message))

    clone = ctx.clone(name)
    approved = clone.rev(APPROVED_REF)
    if not approved:
        return error(f"nothing approved yet (run: omdall check -p {name})")
    if not ctx.state.has_approval(name, approved):
        return error(
            f"approved commit {approved} has no review or waiver record; refusing", approved
        )
    idir = ctx.installed_dir(name)
    if idir is None or not idir.is_dir():
        if not first_install:
            message = (
                f"approved {approved[:12]}, not installed (install with: omdall update -p {name})"
            )
            info(f"{name}: {message}")
            return outcome("not_installed", approved, message)
        say(f"{name}: installing {approved[:12]} (first install)")
        ctx.progress("installing", name)
        if install_new(ctx, name, approved, enable_after=True):
            return outcome("installed", approved)
        return outcome("error", approved, "first install failed")
    before = installed_sha(idir)
    if before == approved:
        info(f"{name}: up to date ({approved[:12]})")
        return outcome("up_to_date", approved)

    installed = Repo(idir)
    # Edited or untracked files survive a fast-forward and were never reviewed.
    dirty = installed.dirty_paths()
    if dirty:
        message = f"the installed copy has local changes ({path_list(dirty)}); not updating"
        warn(f"{name}: {message}")
        return outcome(
            "blocked_dirty", approved, printable(message), dirty=[printable(p) for p in dirty]
        )
    fetched = installed.git("fetch", "--quiet", "origin", APPROVED_REF, check=False)
    if not fetched.ok:
        return error(f"could not fetch gate-approved from the clone{_detail(fetched)}", approved)
    new = installed.rev("FETCH_HEAD")
    if new is None or new != approved:
        return error(
            f"origin gate-approved ({new}) does not match the approved commit "
            f"({approved}); refusing",
            approved,
        )

    say(f"{name}: installing {approved[:12]}")
    ctx.progress("installing", name)
    # No attributes: a filter driver configured on this machine must not
    # rewrite the reviewed files on their way to disk.
    merged = installed.git(
        "merge", "--ff-only", "--quiet", new, check=False, no_attributes=True, no_hooks=True
    )
    if not merged.ok:
        return error(f"cannot fast-forward (local changes in {idir}){_detail(merged)}", approved)
    if installed.head() != new:
        message = "merge landed on the wrong commit; rolling back"
        warn(f"{name}: {message}")
        if _roll_back(ctx, name, installed, before):
            notify(
                ctx,
                f"{name}: update rolled back",
                "The installed copy did not match the approved commit.",
            )
        return outcome("rolled_back", approved, message)

    ctx.progress("validating", name)
    if not proc.run_quiet(["omarchy", "plugin", "validate", str(idir)]):
        message = "manifest validation failed after merge; rolling back"
        warn(f"{name}: {message}")
        _roll_back(ctx, name, installed, before)
        return outcome("rolled_back", approved, message)

    ctx.state.log_event(name, f"installed {new}")
    ensure_hooks(ctx, name)
    return outcome("installed", approved)


def run(ctx: Context, want: str) -> Report:
    ctx.state.root.mkdir(parents=True, exist_ok=True)
    results: list[PluginResult] = []
    names = selected_names(ctx.cfg, want)
    for i, name in enumerate(names, 1):
        ctx.progress("installing", name, i, len(names))
        try:
            results.append(update_one(ctx, name, first_install=bool(want)))
        except (proc.CommandError, OSError) as e:
            warn(f"{name}: {e}")
            results.append(
                PluginResult(name, ctx.manifest_id(name) or None, "error", None, printable(str(e)))
            )

    applied = sum(1 for r in results if r.outcome == "installed")
    if applied:
        if not proc.run_quiet(["omarchy-shell", "shell", "rescanPlugins"]):
            warn("could not ask the shell to rescan plugins")
        notify_close(ctx)
        say(f"Applied {applied} update(s).")
    else:
        say("Nothing to apply.")
    return Report("update", 0, results)
