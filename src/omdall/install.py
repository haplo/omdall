"""First install: put an approved commit into ~/.config/omarchy/plugins/<id>."""

import sys

from . import proc
from .commands import advance_main, disable_plugin, installed_sha
from .context import Context
from .hooks import ensure_hooks
from .output import info, warn
from .plugins import read_manifest


def echo(result: proc.Result) -> None:
    out = (result.stdout + result.stderr).decode("utf-8", "replace").strip()
    if out:
        print(out, file=sys.stderr)


def enable(plugin_id: str, manifest: dict[str, object]) -> None:
    kinds = manifest.get("kinds")
    kinds = kinds if isinstance(kinds, list) else []
    if "bar" in kinds:
        info(f"{plugin_id} is a full-bar plugin; enable it manually with omarchy bar")
        return
    argv = ["omarchy", "plugin", "enable", plugin_id]
    section = ""
    if "bar-widget" in kinds:
        widget = manifest.get("barWidget")
        value = widget.get("defaultSection") if isinstance(widget, dict) else None
        section = value if isinstance(value, str) and value else "center"
        argv += ["--section", section]
    result = proc.run(argv, check=False)
    if not result.ok:
        echo(result)
        warn(f"{plugin_id} is installed but could not be enabled")
    elif section:
        info(f"enabled in the {section} section")


def install_new(ctx: Context, name: str, approved: str, *, enable_after: bool) -> bool:
    """Install a plugin that has no installed copy yet, at its approved commit.

    `omarchy plugin add` clones whatever the gate clone has checked out, so that
    must be the approved commit on the default branch before anything runs.
    True when the installed copy is in place at `approved`.
    """
    clone = ctx.clone(name)
    branch = clone.default_branch()
    advance_main(clone, approved)
    if not branch or clone.current_branch() != branch or clone.head() != approved:
        warn(
            f"{name}: {clone.path} must have {branch or 'the default branch'} checked out "
            f"at the approved commit {approved[:12]}; not installing"
        )
        return False

    result = proc.run(["omarchy", "plugin", "add", str(clone.path), "--yes"], check=False)
    if not result.ok:
        echo(result)
        warn(f"{name}: omarchy plugin add failed")
        return False

    plugin_id = ctx.manifest_id(name)
    idir = ctx.installed_dir(name)
    if idir is None or installed_sha(idir) != approved:
        disable_plugin(plugin_id)
        warn(f"{name}: the installed copy is not at the approved commit {approved[:12]}; disabled")
        return False

    ensure_hooks(ctx, name)
    ctx.state.log_event(name, f"installed {approved}")
    if enable_after:
        enable(plugin_id, read_manifest(idir / "manifest.json") or {})
    else:
        info("installed disabled (--no-enable)")
    return True
