"""adopt: bring a plugin installed outside the gate under it.

The installed copy keeps the files and commit it has: adopting clones upstream
into the gate root, points the installed copy's origin at that clone, and
reviews upstream's current commit. Only `update` ever moves the installed
copy, and nothing here disables it.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import Context
from ..git import Repo
from ..hooks import ensure_hooks
from ..notify import CheckSummary, check_notification, notify
from ..output import (
    AlreadyGuarded,
    GateError,
    IdMismatch,
    NameTaken,
    NotInstalled,
    RefusedUrl,
    info,
    printable,
    say,
    warn,
)
from ..patterns import valid_plugin_id
from ..plugins import manifest_id_of, plugin_names, public_url, read_manifest
from ..results import PluginResult, Report
from ..state import now, one_line, write_atomic
from .add import check_url, clone_name, clone_plugin, guarded_by, is_local_url, url_problem
from .check import check_guarded

# Review outcomes that leave the plugin with an approved commit.
PASSED = ("up_to_date", "approved", "approved_waiver")


@dataclass(frozen=True, slots=True)
class AdoptArgs:
    plugin_id: str
    url: str = ""
    dir: str = ""


@dataclass(frozen=True, slots=True)
class UnguardedRecord:
    """An installed plugin that no clone under the gate root maps to."""

    id: str
    name: str | None
    dir: str
    git: bool
    origin: str | None
    head: str | None
    dirty: bool
    adoptable: bool
    reason: str | None


def has_own_git(directory: Path) -> bool:
    """A git checkout of its own: a `.git` that is not a symbolic link. Without
    the check, git would find a repository further up, such as a dotfiles one."""
    dot_git = directory / ".git"
    return dot_git.exists() and not dot_git.is_symlink() and Repo(directory).is_repo()


def adopt_problem(ctx: Context, is_git: bool, origin: str, override_dir: str = "") -> str | None:
    """Why adopt cannot take this plugin from its own origin, or None."""
    if not is_git:
        return "no_git"
    if not origin:
        return "no_origin"
    if is_local_url(origin):
        return "local_origin"
    if url_problem(origin):
        return "insecure_url"
    try:
        name = clone_name(origin, override_dir)
    except GateError:
        return "name_taken"
    return "name_taken" if ctx.clone_dir(name).exists() else None


def _manifest_name(manifest: dict[str, Any]) -> str | None:
    value = manifest.get("name")
    return printable(value) if isinstance(value, str) else None


def unguarded_record(ctx: Context, directory: Path, manifest: dict[str, Any]) -> UnguardedRecord:
    is_git = has_own_git(directory)
    repo = Repo(directory)
    origin = repo.config_get("remote.origin.url") if is_git else ""
    head = repo.head() if is_git else None
    dirty = bool(repo.dirty_paths()) if is_git else False
    reason = adopt_problem(ctx, is_git, origin)
    return UnguardedRecord(
        id=directory.name,
        name=_manifest_name(manifest),
        dir=str(directory),
        git=is_git,
        origin=printable(public_url(origin)) if origin else None,
        head=head,
        dirty=dirty,
        adoptable=reason is None,
        reason=reason,
    )


def unguarded(ctx: Context) -> list[UnguardedRecord]:
    """Installed plugins with a valid id that no clone under the gate root maps
    to. Cheap: no network. Symbolic links are skipped, never followed."""
    try:
        entries = sorted(ctx.cfg.installed_root.iterdir())
    except OSError:
        return []
    guarded = {ctx.manifest_id(name) for name in plugin_names(ctx.cfg)}
    found: list[UnguardedRecord] = []
    for directory in entries:
        if directory.name.startswith(".") or directory.is_symlink() or not directory.is_dir():
            continue
        manifest_file = directory / "manifest.json"
        if manifest_file.is_symlink():
            continue
        manifest = read_manifest(manifest_file)
        plugin_id = manifest_id_of(manifest)
        if not plugin_id or plugin_id != directory.name or plugin_id in guarded:
            continue
        try:
            found.append(unguarded_record(ctx, directory, manifest or {}))
        except OSError:
            continue
    return found


def _adopted_text(cfg_user: str, plugin_id: str, url: str, previous: str, head: str) -> str:
    lines = [
        f"ADOPTED {now()} {plugin_id} by {one_line(cfg_user)}",
        f"url: {one_line(url)}",
        f"previous-origin: {one_line(previous)}",
        f"installed-head: {head}",
    ]
    return "\n".join(lines) + "\n"


def _point_at_clone(installed: Repo, clone_dir: Path, *, is_git: bool, had_origin: bool) -> None:
    """Make the installed copy fetch from the gate clone. A copy that is not a
    git checkout becomes one at the clone's commit, with its files untouched,
    so whatever differs from that commit shows up as local changes."""
    if had_origin:
        installed.git("remote", "set-url", "origin", str(clone_dir), no_hooks=True)
        return
    if is_git:
        installed.git("remote", "add", "origin", str(clone_dir), no_hooks=True)
        return
    clone = Repo(clone_dir)
    branch = clone.current_branch() or "main"
    installed.git("init", "--quiet", f"--initial-branch={branch}", no_hooks=True)
    installed.git("remote", "add", "origin", str(clone_dir), no_hooks=True)
    installed.git("fetch", "--quiet", "origin", no_hooks=True)
    # A mixed reset moves HEAD and the index, never the files on disk.
    installed.git(
        "reset", "--quiet", f"refs/remotes/origin/{branch}", no_attributes=True, no_hooks=True
    )
    installed.git("branch", "--quiet", f"--set-upstream-to=origin/{branch}", no_hooks=True)


def _undo(installed: Repo, *, is_git: bool, had_origin: bool, previous: str) -> None:
    """Put the installed copy's origin back as it was."""
    if not is_git:
        shutil.rmtree(installed.path / ".git", ignore_errors=True)
    elif had_origin:
        installed.git("remote", "set-url", "origin", previous, check=False, no_hooks=True)
    else:
        installed.git("remote", "remove", "origin", check=False, no_hooks=True)


def resolve(ctx: Context, plugin_id: str) -> Path:
    """The installed copy of `plugin_id`, if adopt may take it."""
    if not valid_plugin_id(plugin_id):
        raise GateError(f"'{printable(plugin_id)}' is not a plugin id omdall can adopt")
    directory = ctx.cfg.installed_root / plugin_id
    if directory.is_symlink():
        raise GateError(f"{directory} is a symbolic link; refusing")
    if not directory.is_dir():
        raise NotInstalled(f"{plugin_id} is not installed (no {directory})")
    if other := guarded_by(ctx, plugin_id):
        raise AlreadyGuarded(f"{plugin_id} is already guarded as '{other}'")
    return directory


def run(ctx: Context, args: AdoptArgs) -> Report:
    if not args.plugin_id:
        raise GateError("adopt needs a plugin id (see: omdall status --json, unguarded)")
    plugin_id = args.plugin_id
    idir = resolve(ctx, plugin_id)
    ctx.progress("adopting", plugin_id)

    installed = Repo(idir)
    is_git = has_own_git(idir)
    previous = installed.config_get("remote.origin.url") if is_git else ""
    url = args.url or previous
    if not url:
        raise RefusedUrl(
            f"{plugin_id} has no origin{'' if is_git else ' (not a git checkout)'}; "
            "pass --url with its upstream repository"
        )
    if not args.url and is_local_url(url):
        raise RefusedUrl(
            f"{plugin_id}'s origin {printable(url)} is a local path, not upstream; "
            "pass --url with its upstream repository"
        )
    check_url(url)
    name = clone_name(url, args.dir)
    clone_dir = ctx.clone_dir(name)
    if clone_dir.exists():
        raise NameTaken(f"'{name}' already exists at {clone_dir}; pass --dir to pick another name")
    head_before = installed.head() if is_git else None

    say(f"Adopting {plugin_id} from {printable(public_url(url))}")
    had_origin = bool(previous)
    pointed = False
    try:
        cloned_id = clone_plugin(ctx, url, name)
        if cloned_id != plugin_id:
            raise IdMismatch(
                f"{printable(public_url(url))} is the plugin '{cloned_id}', not '{plugin_id}'; "
                "clone removed"
            )
        ctx.progress("adopting", name)
        pointed = True
        _point_at_clone(installed, clone_dir, is_git=is_git, had_origin=had_origin)
        write_atomic(
            ctx.state.plugin_dir(name) / "adopted",
            _adopted_text(ctx.cfg.user, plugin_id, url, previous, head_before or ""),
        )
    except BaseException:
        if pointed:
            _undo(installed, is_git=is_git, had_origin=had_origin, previous=previous)
        if clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)
        raise
    ctx.state.log_event(
        name, f"adopted {plugin_id} (previous origin: {previous or '<none>'}, url: {url})"
    )
    info(f"{idir} now fetches from {clone_dir}")

    summary = CheckSummary()
    review = check_guarded(ctx, name, summary)
    ensure_hooks(ctx, name)
    if message := check_notification(summary, ctx.cfg.notify_policy):
        notify(ctx, *message)

    approved = review.sha if review.outcome in PASSED else None
    head_now = installed.head()
    say()
    if approved is None:
        warn(f"{plugin_id} is adopted, but its review did not pass; it stays installed as it was")
        info(f"read why with: omdall status -p {name}")
    else:
        say(f"Adopted {plugin_id} as '{name}'.")
        if head_now != approved:
            info(
                f"the installed commit {(head_now or '(none)')[:12]} was never reviewed; "
                f"install the approved one with: omdall update -p {name}"
            )
    result = PluginResult(
        name,
        plugin_id,
        "adopted",
        review.sha,
        review.message,
        review.cleared,
        review=review.outcome,
    )
    return Report("adopt", 0 if approved else 1, [result], summary)
