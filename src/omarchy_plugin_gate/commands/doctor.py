"""doctor: verify the wiring (hooks, origin, refs, reviewer model and agent)."""

from pathlib import Path

from .. import proc
from ..config import APPROVED_REF
from ..context import Context
from ..git import Repo
from ..hooks import hook_ok, hook_target, install_hook
from ..output import bad, info, ok, say, warn
from ..plugins import same_path, selected_names
from . import path_list


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").rstrip("\n")


def _installed_drift(ctx: Context, name: str, installed: Repo) -> int:
    """Problems with what is on disk in the installed copy."""
    problems = 0
    head = installed.head()
    if head and ctx.state.has_approval(name, head):
        ok("installed commit was reviewed or waived")
    else:
        bad(f"installed commit {head or '(none)'} was never reviewed")
        problems += 1
    dirty = installed.dirty_paths()
    if dirty:
        bad(f"installed copy has local changes: {path_list(dirty)}")
        problems += 1
    else:
        ok("installed copy has no local changes")
    ignored = installed.ignored_paths()
    if ignored:
        info(f"installed copy has ignored files (not reviewed): {path_list(ignored)}")
    return problems


def doctor_one(ctx: Context, name: str, fix: bool) -> bool:
    """True when this plugin's wiring is sound."""
    clone_dir = ctx.clone_dir(name)
    clone = Repo(clone_dir)
    plugin_id = ctx.manifest_id(name)
    idir = ctx.cfg.installed_root / plugin_id if plugin_id else None
    problems = 0
    say(f"{name} ({plugin_id})")

    if (clone_dir / ".git").exists() and clone.is_repo():
        ok("clone is a git repository")
    else:
        bad(f"no git repository at {clone_dir}")
        return False

    branch = clone.default_branch()
    if branch:
        ok(f"default branch: {branch}")
    else:
        bad("cannot determine the default branch")
        problems += 1

    origin = clone.remote_url()
    if origin:
        ok(f"origin: {origin}")
    else:
        bad("clone has no origin")
        problems += 1
    if same_path(origin, clone_dir, base=clone_dir):
        bad("clone's origin points at itself")
        problems += 1

    if clone.rev(APPROVED_REF):
        ok("gate-approved exists")
    else:
        info("no gate-approved yet (the first check will bootstrap it)")

    installed = idir is not None and idir.is_dir()
    if idir is not None and installed:
        inst_origin = Repo(idir).remote_url()
        if same_path(inst_origin, clone_dir, base=idir):
            ok("installed copy tracks the gate clone")
        else:
            bad(
                f"installed copy's origin is '{inst_origin}', not the gate clone — "
                "plain omarchy plugin update would bypass the gate"
            )
            problems += 1
        problems += _installed_drift(ctx, name, Repo(idir))
    else:
        info(f"not installed yet ({idir or ctx.cfg.installed_root / '<no id>'})")

    targets = [("the clone", clone_dir)]
    if idir is not None and installed:
        targets.append(("the installed copy", idir))
    for label, directory in targets:
        if hook_ok(ctx.cfg, directory, name):
            ok(f"tripwire in {label}")
            continue
        problem = install_hook(ctx.cfg, directory, name) if fix else hook_target(directory)[1]
        if problem:
            bad(f"no tripwire in {label}: {problem}")
            problems += 1
        elif fix:
            ok(f"installed tripwire in {label}")
        else:
            bad(f"no current tripwire in {label} (run doctor --fix)")
            problems += 1

    return problems == 0


def run(ctx: Context, want: str, fix: bool) -> int:
    cfg = ctx.cfg
    if not cfg.root.is_dir():
        warn(f"gate root does not exist: {cfg.root}")
        return 1
    failures = 0
    if cfg.config_file.is_file():
        ok(f"config: {cfg.config_file}")
    else:
        info(f"no config file at {cfg.config_file} (defaults apply)")
    opencode = proc.which("opencode")
    if opencode is None:
        bad("opencode is not on PATH; the reviewer cannot run")
        failures += 1
    else:
        ok(f"opencode: {opencode}")
    omarchy = proc.which("omarchy")
    if omarchy is None:
        bad("omarchy is not on PATH; every candidate fails validation")
        failures += 1
    else:
        ok(f"omarchy: {omarchy}")
    if cfg.model:
        models = proc.run(["opencode", "models"], check=False).text.splitlines()
        if cfg.model in models:
            ok(f"reviewer model: {cfg.model}")
        else:
            bad(f"reviewer model {cfg.model} is not a model opencode knows")
            failures += 1
    else:
        info("reviewer model: opencode default (set model in the config file to pin one)")

    agent, src = cfg.agent_file, cfg.agent_src
    if not agent.is_file():
        bad(f"missing reviewer agent: {agent}")
        failures += 1
    elif cfg.agent == "plugin-reviewer" and src.is_file() and _read(agent) != _read(src):
        bad(f"reviewer agent is out of date: {agent} (run: mise run install)")
        failures += 1
    else:
        ok(f"reviewer agent: {agent}")
    say()

    for name in selected_names(cfg, want):
        if not doctor_one(ctx, name, fix):
            failures += 1
        say()

    if failures:
        warn(f"{failures} problem(s)")
        return 1
    say("Everything checks out.")
    return 0
