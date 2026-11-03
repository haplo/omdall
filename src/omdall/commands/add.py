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
from ..notify import CheckSummary, notify
from ..output import (
    AlreadyGuarded,
    AlreadyInstalled,
    GateError,
    NameTaken,
    RefusedUrl,
    indented,
    info,
    printable,
    say,
    warn,
)
from ..plugins import plugin_names
from ..results import PluginResult, Report
from ..review import review
from .check import held_message


@dataclass(frozen=True, slots=True)
class AddArgs:
    url: str
    dir: str = ""
    enable: bool = True


# The transports add clones over, in git's GIT_ALLOW_PROTOCOL spelling. A local
# path counts as file.
ALLOWED_SCHEMES = ("https", "ssh", "file")
GIT_ALLOW_PROTOCOL = ":".join(ALLOWED_SCHEMES)
_SCHEME = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*)://")
_SCP_LIKE = re.compile(r"(?:[^@/:]+@)?[A-Za-z0-9][A-Za-z0-9._-]*:.+")


def insecure_scheme(url: str) -> str | None:
    """`http` or `git` when `url` uses a transport with no authentication."""
    m = _SCHEME.match(url)
    scheme = m.group(1).lower() if m else ""
    return scheme if scheme in ("http", "git") else None


def url_problem(url: str) -> str | None:
    """Why add refuses `url`, or None. Only authenticated transports and local
    repositories: over http:// or git:// anyone on the network path chooses the
    code that is reviewed and installed."""
    if not url:
        return "add needs a git URL"
    if printable(url) != url:
        return f"'{printable(url)}' contains control characters"
    if url.startswith("-"):
        return f"'{url}' looks like an option, not a repository"
    if "::" in url:
        return f"'{url}' names a git transport helper, not a repository"
    if scheme := insecure_scheme(url):
        return (
            f"'{url}' uses {scheme}://, which is not authenticated: anyone on the network "
            "path could choose the code under review; use https:// or ssh://"
        )
    if m := _SCHEME.match(url):
        if m.group(1) in ALLOWED_SCHEMES:
            return None
        return f"'{url}' uses the {m.group(1)}:// transport; use https://, ssh:// or file://"
    if url.startswith("/") or _SCP_LIKE.fullmatch(url):
        return None
    return f"'{url}' is neither a URL nor an absolute path"


def is_local_url(url: str) -> bool:
    """A path or file:// URL: a repository on this machine, not an upstream."""
    if m := _SCHEME.match(url):
        return m.group(1).lower() == "file"
    if not url or url.startswith("-") or "::" in url:
        return False
    return not _SCP_LIKE.fullmatch(url)


def check_url(url: str) -> None:
    """Refuse `url` unless it passes the transport policy and Omarchy's own check."""
    if problem := url_problem(url):
        raise RefusedUrl(problem)
    # Omarchy's own check, the one `omarchy plugin add` runs, when it is there.
    if proc.which("omarchy-git-url-check"):
        result = proc.run(["omarchy-git-url-check", url], check=False)
        if not result.ok:
            echo(result)
            raise RefusedUrl(f"omarchy-git-url-check refused '{url}'")


def clone_name(url: str, override: str = "") -> str:
    name = override or url.rstrip("/").rsplit("/", 1)[-1]
    name = re.sub(r"[^A-Za-z0-9._-]", "-", name.removesuffix(".git"))
    if not name:
        raise GateError(f"cannot derive a directory name from '{url}'; pass --dir")
    if name.startswith("."):
        raise GateError(f"refusing a name starting with a dot: {name}")
    return name


def clone_plugin(ctx: Context, url: str, name: str) -> str:
    """Clone `url` into the gate root as `name`, and return its manifest id.
    The clone is removed again unless it is a valid plugin."""
    clone_dir = ctx.clone_dir(name)
    ctx.cfg.root.mkdir(parents=True, exist_ok=True)
    say(f"Cloning {url} into {clone_dir}")
    ctx.progress("fetching", name)
    # The allow-list also holds if the user's config enables more protocols or a
    # url.insteadOf rewrites the URL.
    result = proc.run(
        ["git", "clone", "--quiet", "--", url, str(clone_dir)],
        check=False,
        env={"GIT_ALLOW_PROTOCOL": GIT_ALLOW_PROTOCOL},
    )
    if not result.ok:
        echo(result)
        raise GateError("clone failed")

    plugin_id = ctx.manifest_id(name)
    if not plugin_id:
        shutil.rmtree(clone_dir)
        raise GateError("no manifest.json id at the repository root; not a plugin")

    ctx.progress("validating", name)
    result = proc.run(["omarchy", "plugin", "validate", str(clone_dir)], check=False)
    if not result.ok:
        shutil.rmtree(clone_dir)
        echo(result)
        raise GateError("manifest validation failed; clone removed")
    return plugin_id


def guarded_by(ctx: Context, plugin_id: str, *, besides: str = "") -> str | None:
    """The clone, other than `besides`, whose manifest id is `plugin_id`."""
    return next(
        (n for n in plugin_names(ctx.cfg) if n != besides and ctx.manifest_id(n) == plugin_id),
        None,
    )


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


def run(ctx: Context, args: AddArgs) -> Report:
    check_url(args.url)
    name = clone_name(args.url, args.dir)
    clone_dir = ctx.clone_dir(name)
    if clone_dir.exists():
        raise NameTaken(
            f"'{name}' already exists at {clone_dir} — review it with: "
            f"omdall check -p {name}, install it with: "
            f"omdall update -p {name}"
        )

    plugin_id = clone_plugin(ctx, args.url, name)
    if _already_installed(plugin_id):
        shutil.rmtree(clone_dir)
        if other := guarded_by(ctx, plugin_id, besides=name):
            raise AlreadyGuarded(
                f"plugin id '{plugin_id}' is already installed and guarded as '{other}' — "
                f"use: omdall check -p {other}"
            )
        raise AlreadyInstalled(
            f"plugin id '{plugin_id}' is already installed — bring it under the gate with: "
            f"omdall adopt {plugin_id}"
        )

    summary = CheckSummary()

    def report(outcome: str, sha: str, message: str | None = None, cleared: int = 0) -> Report:
        result = PluginResult(name, plugin_id, outcome, sha, message, cleared)
        return Report("add", 0 if outcome.startswith("installed") else 1, [result], summary)

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
            f"after reading it, to install anyway: omdall approve {name} && omdall update -p {name}"
        )
        warn(f"{plugin_id} was not installed")
        summary.held.append(name)
        return report("held", head, held_message(ctx, name, head))

    ctx.state.set_marker(name, head, "initial import")
    clone.update_ref(APPROVED_REF, head, None)
    ensure_hooks(ctx, name)
    ncleared = rd.cleared_count()
    if ncleared:
        summary.cleared.append(name)
        info(f"the reviewer cleared {ncleared} structural finding(s): {rd.cleared}")

    say(f"Installing {plugin_id}")
    ctx.progress("installing", name)
    if not install_new(ctx, name, head, enable_after=args.enable):
        notify(ctx, f"{plugin_id}: install failed", f"The clone is kept at {clone_dir}.")
        message = (
            f"{plugin_id} was not installed; the clone is kept at {clone_dir} "
            f"(retry with: omdall update -p {name})"
        )
        warn(message)
        summary.errors.append(name)
        return report("error", head, printable(message), ncleared)

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
    return report("installed" if args.enable else "installed_disabled", head, cleared=ncleared)
