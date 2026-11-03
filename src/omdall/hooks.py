"""The post-merge tripwire: a net for merges that did not come through the gate."""

import shlex
from pathlib import Path

from .config import Config
from .context import Context
from .git import Repo
from .output import printable, warn
from .state import write_atomic

MARK = "omdall"


def _ours(path: Path) -> bool:
    try:
        return MARK in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def hook_target(directory: Path) -> tuple[Path | None, str]:
    """Where this repository's tripwire goes, or why the gate will not write one.

    A hooks directory outside the repository's git directory comes from
    core.hooksPath and is shared with other repositories, so it is left alone.
    So is a post-merge hook the gate did not write."""
    dirs = Repo(directory).hook_dirs()
    if dirs is None:
        return None, "cannot find the git hooks directory"
    hooks, common = (p.resolve() for p in dirs)
    if not hooks.is_relative_to(common):
        return None, (
            f"core.hooksPath is set ({printable(str(hooks))}), so the tripwire was not installed"
        )
    path = hooks / "post-merge"
    if (path.exists() or path.is_symlink()) and not _ours(path):
        return None, f"a post-merge hook of your own exists at {printable(str(path))}"
    return path, ""


def _exec_line(cfg: Config, name: str) -> str:
    """The hook's gate invocation. The root, state and plugin name are fixed when
    the hook is written, so the tripwire uses the same paths as the run that
    installed it and never has to work out the plugin from the merged files."""
    gate = shlex.quote(str(cfg.self_path))
    root = shlex.quote(str(cfg.root))
    state = shlex.quote(str(cfg.state_root))
    log = shlex.quote(str(cfg.state_root / "hooks.log"))
    command = f"{gate} --root {root} --state {state} _post-merge {shlex.quote(name)}"
    return f'exec {command} "$top" >>{log} 2>&1\n'


def hook_text(cfg: Config, name: str) -> str:
    state = shlex.quote(str(cfg.state_root))
    return f"""\
#!/usr/bin/env bash
# Installed by omdall for {printable(name)}. Reviews out-of-band merges.
top=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
mkdir -p {state}
{_exec_line(cfg, name)}"""


def hook_ok(cfg: Config, directory: Path, name: str) -> bool:
    """Installed, pointing at this binary, using this root and state, and naming
    this plugin."""
    path, _problem = hook_target(directory)
    if path is None or not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _exec_line(cfg, name) in text.splitlines(keepends=True)


def install_hook(cfg: Config, directory: Path, name: str) -> str | None:
    """Write the tripwire. Returns why it was not written, or None."""
    if printable(name) != name:
        return f"the plugin name {printable(name)} cannot go into a hook"
    path, problem = hook_target(directory)
    if path is None:
        return problem
    try:
        write_atomic(path, hook_text(cfg, name))
        path.chmod(0o755)
    except OSError as e:
        return f"could not write {printable(str(path))}: {e.strerror or e}"
    return None


def ensure_hooks(ctx: Context, name: str) -> None:
    directories = [ctx.clone_dir(name)]
    installed = ctx.installed_dir(name)
    if installed and installed.is_dir():
        directories.append(installed)
    for directory in directories:
        if hook_ok(ctx.cfg, directory, name):
            continue
        problem = install_hook(ctx.cfg, directory, name)
        if problem:
            warn(f"could not install the tripwire in {directory}: {problem}")


def is_upstream_commit(repo: Repo, sha: str) -> bool:
    """A commit belongs to us if it is not reachable from upstream. Only upstream
    commits are ever rolled back; local work is nobody's business but yours."""
    branch = repo.default_branch()
    if not branch:
        return False
    upstream = repo.upstream(branch)
    return upstream is not None and repo.is_ancestor(sha, upstream)
