"""add: clone, review the initial tree, install, enable only on REVIEW PASS."""

import json
import re
import shutil
from dataclasses import dataclass

from .. import proc
from ..config import APPROVED_REF
from ..context import Context
from ..hooks import ensure_hooks
from ..install import echo, install_new
from ..notify import notify
from ..output import GateError, indented, info, say
from ..review import review


@dataclass(frozen=True, slots=True)
class AddArgs:
    url: str
    dir: str = ""
    enable: bool = True


def clone_name(url: str, override: str = "") -> str:
    name = override or url.rstrip("/").rsplit("/", 1)[-1]
    name = re.sub(r"[^A-Za-z0-9._-]", "-", name.removesuffix(".git"))
    if not name:
        raise GateError(f"cannot derive a directory name from '{url}'; pass --dir")
    if name.startswith("."):
        raise GateError(f"refusing a name starting with a dot: {name}")
    return name


def _already_installed(plugin_id: str) -> bool:
    result = proc.run(["omarchy", "plugin", "list", "--json"], check=False)
    if not result.ok:
        return False
    try:
        entries = json.loads(result.stdout)
    except ValueError:
        return False
    return isinstance(entries, list) and any(
        isinstance(e, dict) and e.get("id") == plugin_id for e in entries
    )


def run(ctx: Context, args: AddArgs) -> int:
    if not args.url:
        raise GateError("add needs a git URL")
    name = clone_name(args.url, args.dir)
    clone_dir = ctx.clone_dir(name)
    if clone_dir.exists():
        raise GateError(
            f"'{name}' already exists at {clone_dir} — review it with: "
            f"omarchy-plugin-gate check -p {name}, install it with: "
            f"omarchy-plugin-gate update -p {name}"
        )

    ctx.cfg.root.mkdir(parents=True, exist_ok=True)
    say(f"Cloning {args.url} into {clone_dir}")
    result = proc.run(["git", "clone", "--quiet", "--", args.url, str(clone_dir)], check=False)
    if not result.ok:
        echo(result)
        raise GateError("clone failed")

    plugin_id = ctx.manifest_id(name)
    if not plugin_id:
        shutil.rmtree(clone_dir)
        raise GateError("no manifest.json id at the repository root; not a plugin")

    result = proc.run(["omarchy", "plugin", "validate", str(clone_dir)], check=False)
    if not result.ok:
        shutil.rmtree(clone_dir)
        echo(result)
        raise GateError("manifest validation failed; clone removed")

    if _already_installed(plugin_id):
        raise GateError(
            f"plugin id '{plugin_id}' is already installed — "
            f"use: omarchy-plugin-gate check -p {name}"
        )

    clone = ctx.clone(name)
    head = clone.head()
    if not head:
        raise GateError(f"{clone_dir} has no HEAD commit")
    rd = ctx.state.review_dir(name, head)
    say(f"Reviewing the initial import of {plugin_id} ({head})")
    if not review(ctx, name, clone, None, head):
        ctx.state.record_held(name, head)
        ctx.state.log_event(name, "add: initial review failed")
        notify(ctx, f"{plugin_id}: review failed", "Nothing was installed. Open status to see why.")
        say()
        say("Held back. Reasons:")
        indented(rd.verdict_lines()[1:], 2)
        info(f"patch: {rd.patch}")
        info(
            f"after reading it, to install anyway: omarchy-plugin-gate approve {name} "
            f"&& omarchy-plugin-gate update -p {name}"
        )
        raise GateError(f"{plugin_id} was not installed")

    ctx.state.set_marker(name, head, "initial import")
    clone.update_ref(APPROVED_REF, head, None)
    ensure_hooks(ctx, name)
    ncleared = rd.cleared_count()
    if ncleared:
        info(f"the reviewer cleared {ncleared} structural finding(s): {rd.cleared}")

    say(f"Installing {plugin_id}")
    if not install_new(ctx, name, head, enable_after=args.enable):
        notify(ctx, f"{plugin_id}: install failed", f"The clone is kept at {clone_dir}.")
        raise GateError(
            f"{plugin_id} was not installed; the clone is kept at {clone_dir} "
            f"(retry with: omarchy-plugin-gate update -p {name})"
        )

    suffix = (
        f" The reviewer cleared {ncleared} structural finding(s); check status." if ncleared else ""
    )
    if args.enable:
        notify(ctx, f"{plugin_id}: installed", f"Reviewed, installed and enabled.{suffix}")
    else:
        notify(ctx, f"{plugin_id}: installed", f"Reviewed and installed, left disabled.{suffix}")
    say()
    say(f"Done. {plugin_id} at {head[:12]} (installed from the reviewed clone)")
    info(f"upstream clone: {clone_dir}")
    info(f"review: {rd.path}")
    return 0
