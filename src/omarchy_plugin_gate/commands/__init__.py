"""Subcommands. Each takes a Context and returns an exit status."""

from pathlib import Path

from .. import proc
from ..git import Repo
from ..output import printable


def advance_main(repo: Repo, sha: str) -> None:
    """Advance the clone's checkout so a plain `git pull` later is a no-op.

    Only when it is safe: on the default branch, clean tree, fast-forwardable.
    Never required for correctness (gate-approved is the authoritative ref).
    """
    current = repo.current_branch()
    if not current or current != repo.default_branch():
        return
    if not repo.is_clean() or not repo.is_ancestor("HEAD", sha):
        return
    repo.ok("merge", "--ff-only", "--quiet", sha, no_attributes=True, no_hooks=True)


def installed_sha(directory: Path | None) -> str | None:
    if directory is None or not directory.is_dir():
        return None
    return Repo(directory).head()


def path_list(paths: list[str], limit: int = 3) -> str:
    """The first few paths, escaped, for one line of output."""
    shown = ", ".join(printable(p) for p in paths[:limit])
    more = len(paths) - limit
    return f"{shown} and {more} more" if more > 0 else shown


def disable_plugin(plugin_id: str) -> None:
    if plugin_id and proc.which("omarchy"):
        proc.run_quiet(["omarchy", "plugin", "disable", plugin_id])
