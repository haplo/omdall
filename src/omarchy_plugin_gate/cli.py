"""Command-line entry point."""

import argparse
import io
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from . import __version__, proc
from .commands import add, approve, check, complete, doctor, post_merge, status, update
from .config import SETTING_FIELDS, Config, Overrides, option_flag
from .context import Context
from .output import GateError, say, warn

USAGE = """\
omarchy-plugin-gate — review Omarchy plugin updates before they reach the shell

usage: omarchy-plugin-gate [options] <command> [command options] [options]

  add <git-url> [--dir NAME] [--no-enable]
      Clone into the gate root, review the initial tree, install it disabled,
      enable it only on REVIEW PASS.

  check [-p NAME]
      Fetch upstream, review new commits, stage approved ones. Never installs.
      Hard structural failures are held without a model call; other structural
      findings are listed, one per line, and go to the reviewer, which must
      clear each one.

  approve <name> [--sha SHA] [--reason TEXT] [--show] [-n|--dry-run]
      One-time human approval for a candidate the gate held back. Shows the
      verdict and findings, asks why (the answer may be empty), and advances
      gate-approved. Run update afterwards. --show prints the patch with
      control characters escaped.

  update [-p NAME]
      Apply approved commits to ~/.config/omarchy/plugins/<id> and rescan.
      With -p, a plugin that is approved but not installed yet (say, approved
      by hand after add held it back) is installed and enabled. An installed
      copy with modified or untracked files is not updated.

  status [-p NAME]
      What is installed, approved, upstream, and held, plus local changes in
      the installed copy and an installed commit that was never reviewed.

  doctor [-p NAME] [--fix]
      Verify the wiring (hooks, origin, refs, reviewer model) and that the
      installed copy is a reviewed commit with no local changes. --fix
      installs missing hooks.

Options, before or after the command. Each overrides its environment variable:
  --root DIR         OMARCHY_PLUGIN_GATE_ROOT       gate root
                                                    (default ~/Work/omarchy-plugins)
  --state DIR        OMARCHY_PLUGIN_GATE_STATE      evidence and markers
                                                    (default ~/.local/state/omarchy-plugin-gate)
  --agent NAME       OMARCHY_PLUGIN_GATE_AGENT      reviewer agent (default plugin-reviewer)
  --model ID         OMARCHY_PLUGIN_GATE_MODEL      reviewer model (default: OpenCode's default)
  --notify POLICY    OMARCHY_PLUGIN_GATE_NOTIFY     all|ready|none (default all)
  --timeout SECONDS  OMARCHY_PLUGIN_GATE_TIMEOUT    reviewer timeout (default 420)
  --max-patch BYTES  OMARCHY_PLUGIN_GATE_MAX_PATCH  patch size limit (default 2097152)

Config file, lowest priority: $XDG_CONFIG_HOME/omarchy-plugin-gate/config.toml
(default ~/.config/omarchy-plugin-gate/config.toml). Its keys are the option
names without the dashes in front: root, state, agent, model, notify, timeout,
max-patch.
"""


COMMANDS = ("add", "approve", "check", "update", "status", "doctor")


class _Parser(argparse.ArgumentParser):
    """argparse that reports errors like the rest of the gate (exit 1, no usage dump)."""

    def error(self, message: str) -> NoReturn:
        raise GateError(message)


SETTING_FLAGS = {option_flag(field): field for field in SETTING_FIELDS}


def _setting_options(p: argparse.ArgumentParser) -> None:
    for name, field in SETTING_FLAGS.items():
        p.add_argument(name, dest=field, default=None)


def _parser(prog: str) -> _Parser:
    p = _Parser(prog=f"omarchy-plugin-gate {prog}", add_help=False, allow_abbrev=False)
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
    p = _Parser(prog="omarchy-plugin-gate", add_help=False, allow_abbrev=False)
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
        case _:
            _plugin_option(p)
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
        ("-p", "plugin"),
        ("--plugin", "plugin"),
        ("--sha", "sha"),
    ):
        if flag in args and getattr(ns, attr, None) == "":
            raise GateError(f"{flag} needs a value")
    return ns


def _context(self_path: Path, *namespaces: argparse.Namespace) -> Context:
    return Context.create(Config.from_env(os.environ, self_path, _overrides(*namespaces)))


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
            return post_merge.run(_context(self_path, lead), args[0], args[1])
        case "_complete":
            # Called on Tab: answer in plain lines, and never print a diagnostic
            # or fail the user's shell, whatever the config says.
            try:
                return complete.run(_context(self_path, lead), args)
            except Exception:  # noqa: BLE001 - completion must never fail
                return 0
        case "add":
            if (ns := _parse(cmd, args)) is None:
                return 0
            return add.run(
                _context(self_path, lead, ns),
                add.AddArgs(ns.url, dir=ns.dir, enable=not ns.no_enable),
            )
        case "approve":
            if (ns := _parse(cmd, args)) is None:
                return 0
            if ns.name and ns.plugin:
                raise GateError(f"unexpected argument: {ns.name}")
            return approve.run(
                _context(self_path, lead, ns),
                approve.ApproveArgs(
                    ns.name or ns.plugin,
                    sha=ns.sha,
                    reason=ns.reason,
                    show=ns.show,
                    dry_run=ns.dry_run,
                ),
            )
        case "check" | "update" | "status" | "doctor":
            if (ns := _parse(cmd, args)) is None:
                return 0
            ctx = _context(self_path, lead, ns)
            if cmd == "check":
                return check.run(ctx, ns.plugin)
            if cmd == "update":
                return update.run(ctx, ns.plugin)
            if cmd == "status":
                return status.run(ctx, ns.plugin)
            return doctor.run(ctx, ns.plugin, ns.fix)
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
        return 1
    except proc.CommandError as e:
        warn(str(e))
        return 1
    except KeyboardInterrupt:
        return 130
