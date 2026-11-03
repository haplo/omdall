"""doctor: verify the wiring (hooks, origin, refs, reviewer model and agent)."""

from pathlib import Path

from .. import proc
from ..config import APPROVED_REF
from ..context import Context
from ..git import Repo
from ..hooks import hook_ok, hook_target, install_hook
from ..output import bad, info, ok, printable, say, warn
from ..plugins import same_path, selected_names
from ..results import DoctorResult, Report
from . import path_list
from .add import insecure_scheme


class Findings:
    """What doctor prints, and the problems it records for --json."""

    def __init__(self) -> None:
        self.results: list[DoctorResult] = []
        self.name: str | None = None

    def good(self, message: str) -> None:
        ok(message)

    def problem(self, check: str, message: str) -> None:
        bad(message)
        self.results.append(DoctorResult(self.name, check, False, printable(message)))

    def fixed(self, check: str, message: str) -> None:
        ok(message)
        self.results.append(DoctorResult(self.name, check, True, printable(message), fixed=True))

    def problems(self, name: str | None) -> int:
        return sum(1 for r in self.results if r.name == name and not r.ok)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").rstrip("\n")


def _installed_drift(ctx: Context, name: str, installed: Repo, f: Findings) -> None:
    """Problems with what is on disk in the installed copy."""
    head = installed.head()
    if head and ctx.state.has_approval(name, head):
        f.good("installed commit was reviewed or waived")
    else:
        f.problem("installed_reviewed", f"installed commit {head or '(none)'} was never reviewed")
    dirty = installed.dirty_paths()
    if dirty:
        f.problem("installed_clean", f"installed copy has local changes: {path_list(dirty)}")
    else:
        f.good("installed copy has no local changes")
    ignored = installed.ignored_paths()
    if ignored:
        info(f"installed copy has ignored files (not reviewed): {path_list(ignored)}")


def doctor_one(ctx: Context, name: str, fix: bool, f: Findings) -> None:
    clone_dir = ctx.clone_dir(name)
    clone = Repo(clone_dir)
    plugin_id = ctx.manifest_id(name)
    idir = ctx.cfg.installed_root / plugin_id if plugin_id else None
    f.name = name
    say(f"{name} ({plugin_id})")

    if (clone_dir / ".git").exists() and clone.is_repo():
        f.good("clone is a git repository")
    else:
        f.problem("clone", f"no git repository at {clone_dir}")
        return

    branch = clone.default_branch()
    if branch:
        f.good(f"default branch: {branch}")
    else:
        f.problem("branch", "cannot determine the default branch")

    origin = clone.remote_url()
    if not origin:
        f.problem("origin", "clone has no origin")
    elif scheme := insecure_scheme(origin):
        f.problem(
            "origin",
            f"origin {printable(origin)} uses {scheme}://, which is not authenticated: anyone "
            "on the network path could choose the code under review "
            f"(fix: git -C {clone_dir} remote set-url origin <https or ssh URL>)",
        )
    else:
        f.good(f"origin: {origin}")
    if same_path(origin, clone_dir, base=clone_dir):
        f.problem("origin", "clone's origin points at itself")

    if clone.rev(APPROVED_REF):
        f.good("gate-approved exists")
    else:
        info("no gate-approved yet (the first check will bootstrap it)")

    installed = idir is not None and idir.is_dir()
    if idir is not None and installed:
        inst_origin = Repo(idir).remote_url()
        if same_path(inst_origin, clone_dir, base=idir):
            f.good("installed copy tracks the gate clone")
        else:
            f.problem(
                "installed_origin",
                f"installed copy's origin is '{inst_origin}', not the gate clone — "
                "plain omarchy plugin update would bypass the gate",
            )
        _installed_drift(ctx, name, Repo(idir), f)
    else:
        info(f"not installed yet ({idir or ctx.cfg.installed_root / '<no id>'})")

    targets = [("the clone", "hook_clone", clone_dir)]
    if idir is not None and installed:
        targets.append(("the installed copy", "hook_installed", idir))
    for label, check, directory in targets:
        if hook_ok(ctx.cfg, directory, name):
            f.good(f"tripwire in {label}")
            continue
        problem = install_hook(ctx.cfg, directory, name) if fix else hook_target(directory)[1]
        if problem:
            f.problem(check, f"no tripwire in {label}: {problem}")
        elif fix:
            f.fixed(check, f"installed tripwire in {label}")
        else:
            f.problem(check, f"no current tripwire in {label} (run doctor --fix)")


def _report(f: Findings, failures: int) -> Report:
    return Report("doctor", 1 if failures else 0, f.results)


def run(ctx: Context, want: str, fix: bool) -> Report:
    cfg = ctx.cfg
    f = Findings()
    if not cfg.root.is_dir():
        message = f"gate root does not exist: {cfg.root}"
        warn(message)
        f.results.append(DoctorResult(None, "root", False, printable(message)))
        return _report(f, 1)
    if fix:
        ctx.progress("doctor")
    if cfg.config_file.is_file():
        f.good(f"config: {cfg.config_file}")
    else:
        info(f"no config file at {cfg.config_file} (defaults apply)")
    opencode = proc.which("opencode")
    if opencode is None:
        f.problem("opencode", "opencode is not on PATH; the reviewer cannot run")
    else:
        f.good(f"opencode: {opencode}")
    omarchy = proc.which("omarchy")
    if omarchy is None:
        f.problem("omarchy", "omarchy is not on PATH; every candidate fails validation")
    else:
        f.good(f"omarchy: {omarchy}")
    if cfg.model:
        models = proc.run(["opencode", "models"], check=False).text.splitlines()
        if cfg.model in models:
            f.good(f"reviewer model: {cfg.model}")
        else:
            f.problem("model", f"reviewer model {cfg.model} is not a model opencode knows")
    else:
        info("reviewer model: opencode default (set model in the config file to pin one)")

    agent, src = cfg.agent_file, cfg.agent_src
    if not agent.is_file():
        f.problem("agent", f"missing reviewer agent: {agent}")
    elif cfg.agent == "omdall-reviewer" and src.is_file() and _read(agent) != _read(src):
        f.problem("agent", f"reviewer agent is out of date: {agent} (run: mise run install)")
    else:
        f.good(f"reviewer agent: {agent}")
    say()
    failures = f.problems(None)

    for name in selected_names(cfg, want):
        doctor_one(ctx, name, fix, f)
        if f.problems(name):
            failures += 1
        say()

    if failures:
        warn(f"{failures} problem(s)")
        return _report(f, failures)
    say("Everything checks out.")
    return _report(f, 0)
