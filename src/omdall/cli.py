"""Command-line entry point."""

import argparse
import io
import os
import sys
from collections.abc import Generator, Sequence
from contextlib import contextmanager, nullcontext, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, TextIO

from . import __version__, proc
from .commands import (
    add,
    adopt,
    approve,
    check,
    complete,
    doctor,
    post_merge,
    reviews,
    status,
    update,
)
from .config import SETTING_FIELDS, Config, Overrides, option_flag
from .context import Context
from .notify import CheckSummary
from .output import GateError, emit_json, printable, say, warn
from .results import Report

USAGE = """\
omdall — review Omarchy plugin updates before they reach the shell

usage: omdall [options] <command> [command options] [options]

  add <git-url> [--dir NAME] [--no-enable] [--no-wait] [--json]
      Clone into the gate root, review the initial tree, install it disabled,
      enable it only on REVIEW PASS. The URL must be https://, ssh://,
      user@host:path, file:// or an absolute path.

  adopt <id> [--url URL] [--dir NAME] [--no-wait] [--json]
      Bring a plugin installed with omarchy plugin add under the gate: clone
      its origin (or --url) into the gate root, point the installed copy at
      the clone, and review upstream's current commit. The installed copy
      keeps its files and commit, and stays enabled; update moves it.
      status --json lists the candidates under "unguarded".

  check [-p NAME] [--no-wait] [--json]
      Fetch upstream, review new commits, stage approved ones. Never installs.
      Hard structural failures are held without a model call; other structural
      findings are listed, one per line, and go to the reviewer, which must
      clear each one.

  approve <name> [--sha SHA] [--reason TEXT] [--show] [-n|--dry-run] [--no-wait]
      One-time human approval for a candidate the gate held back. Shows the
      verdict and findings, asks why (the answer may be empty), and advances
      gate-approved. Run update afterwards. --show prints the patch from
      gate-approved to the candidate, with control characters escaped. A
      commit with no review verdict needs --show or --reason.

  update [-p NAME] [--no-wait] [--json]
      Apply approved commits to ~/.config/omarchy/plugins/<id> and rescan.
      With -p, a plugin that is approved but not installed yet (say, approved
      by hand after add held it back) is installed and enabled. An installed
      copy with modified or untracked files is not updated.

  status [-p NAME] [--json]
      What is installed, approved, upstream, and held, plus local changes in
      the installed copy and an installed commit that was never reviewed.

  reviews [<name>] [-p NAME] [--json]
      The evidence recorded for each candidate, newest first: verdict,
      reasons, findings, how it was approved, and where the files are.

  doctor [-p NAME] [--fix] [--no-wait] [--json]
      Verify the wiring (hooks, origin, refs, reviewer model) and that the
      installed copy is a reviewed commit with no local changes. --fix
      installs missing hooks, but never over a post-merge hook of your own or
      into a core.hooksPath directory.

add, adopt, approve, check, update, doctor --fix and the tripwire run one at
a time; a second run waits for the first to finish. With --no-wait it exits
75 instead, having done nothing. status, reviews, doctor and approve
--dry-run never wait.

--json prints one JSON object on stdout (schema 1; fields are only added).
With add, adopt, check, update and doctor everything else goes to stderr, and the
object lists each plugin's outcome, also when the exit status is 1. A refusal
or a busy lock prints {"schema": 1, "error": ..., "code": ...} on stdout as
well as the message on stderr. Every run that takes the lock is published in
<state>/activity.json.

Exit status: 0 done; 1 failed, refused, or found problems; 75 another run
holds the lock (--no-wait only); 130 interrupted.

Options, before or after the command. Each overrides its environment variable:
  --root DIR         OMDALL_ROOT       gate root (default ~/Work/omarchy-plugins)
  --state DIR        OMDALL_STATE      evidence and markers
                                       (default ~/.local/state/omdall)
  --agent NAME       OMDALL_AGENT      reviewer agent (default omdall-reviewer)
  --model ID         OMDALL_MODEL      reviewer model (default: OpenCode's default)
  --notify POLICY    OMDALL_NOTIFY     all|ready|none (default all)
  --timeout SECONDS  OMDALL_TIMEOUT    reviewer timeout (default 420)
  --max-patch BYTES  OMDALL_MAX_PATCH  patch size limit (default 2097152)

Config file, lowest priority: $XDG_CONFIG_HOME/omdall/config.toml
(default ~/.config/omdall/config.toml). Its keys are the option names without
the dashes in front: root, state, agent, model, notify, timeout, max-patch.
"""


COMMANDS = ("add", "adopt", "approve", "check", "update", "status", "reviews", "doctor")


class _Parser(argparse.ArgumentParser):
    """argparse that reports errors like the rest of the gate (exit 1, no usage dump)."""

    def error(self, message: str) -> NoReturn:
        raise GateError(message)


SETTING_FLAGS = {option_flag(field): field for field in SETTING_FIELDS}


def _setting_options(p: argparse.ArgumentParser) -> None:
    for name, field in SETTING_FLAGS.items():
        p.add_argument(name, dest=field, default=None)


def _parser(prog: str) -> _Parser:
    p = _Parser(prog=f"omdall {prog}", add_help=False, allow_abbrev=False)
    p.add_argument("-h", "--help", action="store_true")
    _setting_options(p)
    return p


def _split_settings(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """Separate the setting options given before the command from the rest."""
    i = 0
    while i < len(argv):
        name, eq, _ = argv[i].partition("=")
        if name not in SETTING_FLAGS:
            break
        i += 1 if eq else 2
    return list(argv[:i]), list(argv[i:])


def _parse_settings(args: Sequence[str]) -> argparse.Namespace:
    p = _Parser(prog="omdall", add_help=False, allow_abbrev=False)
    _setting_options(p)
    return p.parse_args(list(args))


def _overrides(*namespaces: argparse.Namespace) -> Overrides:
    """Merge setting options; a later namespace wins over an earlier one."""
    values: dict[str, str] = {}
    for ns in namespaces:
        for name, field in SETTING_FLAGS.items():
            value = getattr(ns, field, None)
            if value is None:
                continue
            if value == "":
                raise GateError(f"{name} needs a value")
            values[field] = value
    return Overrides(**values)


def _plugin_option(p: argparse.ArgumentParser) -> None:
    p.add_argument("-p", "--plugin", default="")


def command_parser(prog: str) -> _Parser:
    """The parser for one subcommand. Completion tests read its options."""
    p = _parser(prog)
    match prog:
        case "add":
            p.add_argument("url", nargs="?", default="")
            p.add_argument("--dir", default="")
            p.add_argument("--no-enable", action="store_true")
        case "adopt":
            p.add_argument("plugin_id", nargs="?", default="")
            p.add_argument("--url", default="")
            p.add_argument("--dir", default="")
        case "approve":
            p.add_argument("name", nargs="?", default="")
            _plugin_option(p)
            p.add_argument("--sha", default="")
            p.add_argument("--reason", nargs="?", const="", default=None)
            p.add_argument("--show", action="store_true")
            p.add_argument("-n", "--dry-run", action="store_true")
        case "doctor":
            _plugin_option(p)
            p.add_argument("--fix", action="store_true")
        case "reviews":
            p.add_argument("name", nargs="?", default="")
            _plugin_option(p)
        case _:
            _plugin_option(p)
    if prog not in ("status", "reviews"):
        p.add_argument("--no-wait", action="store_true")
    if prog != "approve":
        p.add_argument("--json", action="store_true")
    return p


def _parse(prog: str, args: Sequence[str]) -> argparse.Namespace | None:
    """Parse one subcommand's arguments, or print usage and return None for --help."""
    p = command_parser(prog)
    ns = p.parse_args(list(args))
    if ns.help:
        say(USAGE.rstrip("\n"))
        return None
    for flag, attr in (
        ("--dir", "dir"),
        ("--url", "url"),
        ("-p", "plugin"),
        ("--plugin", "plugin"),
        ("--sha", "sha"),
    ):
        if flag in args and getattr(ns, attr, None) == "":
            raise GateError(f"{flag} needs a value")
    return ns


@contextmanager
def _json_errors(enabled: bool, out: TextIO) -> Generator[None]:
    """With --json, a failure is also a JSON object on stdout, so a caller that
    reads stdout never has to parse a message. The error still propagates."""
    try:
        yield
    except (GateError, proc.CommandError) as e:
        if enabled:
            code = e.code if isinstance(e, GateError) else "error"
            emit_json({"error": printable(str(e)), "code": code}, file=out)
        raise


@contextmanager
def _json_output(enabled: bool) -> Generator[TextIO]:
    """With --json, stdout is kept for the one JSON object: everything else the
    command prints goes to stderr. Yields the real stdout."""
    out = sys.stdout
    with _json_errors(enabled, out), redirect_stdout(sys.stderr) if enabled else nullcontext():
        yield out


def _context(self_path: Path, *namespaces: argparse.Namespace) -> Context:
    return Context.create(Config.from_env(os.environ, self_path, _overrides(*namespaces)))


@dataclass(slots=True)
class _Run:
    """How a locked run ended, for activity.json. Anything that escapes without
    setting `exit` counts as a failure."""

    exit: int = 1
    summary: CheckSummary | None = None

    def done(self, report: Report) -> Report:
        self.exit, self.summary = report.exit, report.summary
        return report


@contextmanager
def _locked(ctx: Context, command: str, *, wait: bool = True) -> Generator[_Run]:
    """Hold the state lock for one command, and publish its start and end in
    activity.json, however it ends."""
    with ctx.state.lock(wait=wait):
        run = _Run()
        ctx.activity.start(command)
        try:
            yield run
        except GateError as e:
            run.exit = e.exit_code
            raise
        except KeyboardInterrupt:
            run.exit = 130
            raise
        finally:
            ctx.activity.finish(run.exit, run.summary)


def _action(ctx: Context, cmd: str, ns: argparse.Namespace) -> Report:
    if cmd == "doctor" and not ns.fix:
        return doctor.run(ctx, ns.plugin, fix=False)
    with _locked(ctx, cmd, wait=not ns.no_wait) as run:
        match cmd:
            case "add":
                report = add.run(ctx, add.AddArgs(ns.url, dir=ns.dir, enable=not ns.no_enable))
            case "adopt":
                report = adopt.run(ctx, adopt.AdoptArgs(ns.plugin_id, url=ns.url, dir=ns.dir))
            case "check":
                report = check.run(ctx, ns.plugin)
            case "update":
                report = update.run(ctx, ns.plugin)
            case _:
                report = doctor.run(ctx, ns.plugin, fix=True)
        return run.done(report)


def dispatch(self_path: Path, argv: Sequence[str]) -> int:
    leading, rest = _split_settings(argv)
    lead = _parse_settings(leading)
    cmd, args = (rest[0], rest[1:]) if rest else ("", [])
    match cmd:
        case "" | "-h" | "--help" | "help":
            say(USAGE.rstrip("\n"))
            return 0
        case "--version":
            say(__version__)
            return 0
        case "_post-merge":
            if len(args) != 2:
                raise GateError("_post-merge needs a plugin name and a directory")
            ctx = _context(self_path, lead)
            with _locked(ctx, "tripwire") as run:
                run.exit = post_merge.run(ctx, args[0], args[1])
                return run.exit
        case "_complete":
            # Called on Tab: answer in plain lines, and never print a diagnostic
            # or fail the user's shell, whatever the config says.
            try:
                return complete.run(_context(self_path, lead), args)
            except Exception:  # noqa: BLE001 - completion must never fail
                return 0
        case "status" | "reviews":
            with _json_errors("--json" in args, sys.stdout):
                if (ns := _parse(cmd, args)) is None:
                    return 0
                ctx = _context(self_path, lead, ns)
                if cmd == "status":
                    return status.run(ctx, ns.plugin, as_json=ns.json)
                if ns.name and ns.plugin:
                    raise GateError(f"unexpected argument: {ns.name}")
                return reviews.run(ctx, ns.name or ns.plugin, as_json=ns.json)
        case "approve":
            if (ns := _parse(cmd, args)) is None:
                return 0
            if ns.name and ns.plugin:
                raise GateError(f"unexpected argument: {ns.name}")
            ctx = _context(self_path, lead, ns)
            approve_args = approve.ApproveArgs(
                ns.name or ns.plugin,
                sha=ns.sha,
                reason=ns.reason,
                show=ns.show,
                dry_run=ns.dry_run,
            )
            if ns.dry_run:
                return approve.run(ctx, approve_args)
            with _locked(ctx, cmd, wait=not ns.no_wait) as run:
                run.exit = approve.run(ctx, approve_args)
                return run.exit
        case "add" | "adopt" | "check" | "update" | "doctor":
            as_json = "--json" in args
            with _json_output(as_json) as out:
                if (ns := _parse(cmd, args)) is None:
                    return 0
                report = _action(_context(self_path, lead, ns), cmd, ns)
            if as_json:
                emit_json(report.json(), file=out)
            return report.exit
        case _:
            warn(f"unknown command: {cmd}")
            print(USAGE.rstrip("\n"), file=sys.stderr)
            return 1


def main(self_path: Path, argv: Sequence[str] | None = None) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)
    try:
        return dispatch(self_path, sys.argv[1:] if argv is None else argv)
    except GateError as e:
        warn(str(e))
        return e.exit_code
    except proc.CommandError as e:
        warn(str(e))
        return 1
    except KeyboardInterrupt:
        return 130
