"""approve: a one-time human approval for a candidate the gate held back."""

import sys
from dataclasses import dataclass

from .. import mechanics
from ..config import APPROVED_REF
from ..context import Context
from ..hooks import ensure_hooks
from ..output import GateError, indented, info, printable, safe_text, say, warn
from ..plugins import selected_names
from ..state import one_line, read_lines
from . import advance_main


@dataclass(frozen=True, slots=True)
class ApproveArgs:
    plugin: str
    sha: str = ""
    reason: str | None = None
    show: bool = False
    dry_run: bool = False


def run(ctx: Context, args: ApproveArgs) -> int:
    if not args.plugin:
        raise GateError("approve needs a plugin name")
    name = selected_names(ctx.cfg, args.plugin)[0]
    clone = ctx.clone(name)
    held = ctx.state.held(name)

    if args.sha:
        sha = clone.commit(args.sha)
        if not sha:
            raise GateError(f"'{args.sha}' is not a commit in {clone.path}")
    else:
        if not held:
            raise GateError(f"{name}: nothing held back; run: omarchy-plugin-gate check -p {name}")
        sha = clone.commit(held.sha)
        if not sha:
            raise GateError(f"{name}: held commit {held.sha[:12]} is not in {clone.path}")

    # Approve only what upstream actually served. Local commits are the
    # tripwire's business, and an orphaned commit is not something to install.
    branch = clone.default_branch()
    upstream = clone.upstream(branch) if branch else None
    if upstream and not clone.is_ancestor(sha, upstream):
        raise GateError(f"{name}: {sha[:12]} is not reachable from origin/{branch} — refusing")

    rd = ctx.state.review_dir(name, sha)
    say(f"{name}: candidate {sha[:12]}")
    verdict = rd.verdict_lines()
    if verdict:
        info(f"verdict   {printable(verdict[0])}")
        indented(verdict[1:6])
    else:
        warn(f"{name}: no review verdict recorded for {sha[:12]}")
    mech = read_lines(rd.mech)
    if rd.mech.is_file():
        if mechanics.PASS_LINE in mech:
            info(f"checks    {mechanics.PASS_LINE}")
        else:
            info("checks    hard structural failures:")
            indented(mech)
    findings = read_lines(rd.findings)
    if findings:
        info("findings  structural findings for the reviewer:")
        indented(findings)
    if rd.patch.is_file():
        info(f"patch     {rd.patch}")
    if held and held.sha == sha:
        reasons = held.reasons[:5]
        if "".join(reasons).strip():
            info(f"held      {printable(reasons[0])}")
            indented(reasons[1:])

    # What this approval lets through is the diff from where gate-approved is
    # now, which is not necessarily what the recorded review covered.
    old = clone.rev(APPROVED_REF)
    fresh = clone.diff(old or clone.empty_tree, sha)
    stored = rd.patch.read_bytes() if rd.patch.is_file() else None
    if stored != fresh:
        warn(
            f"{name}: the recorded review covered a different diff than this approval "
            "(base moved or evidence missing)"
        )

    if args.show:
        say()
        say(f"--- patch {old[:12] if old else '(empty tree)'}..{sha[:12]} ---")
        # The patch is the plugin author's bytes: escape control characters so
        # it cannot rewrite the screen or reach the terminal's clipboard.
        say(safe_text(fresh.decode("utf-8", "replace").removesuffix("\n")))
        say("--- end patch ---")

    if old == sha and ctx.state.has_approval(name, sha):
        say(f"{name}: {sha[:12]} is already approved; nothing to do")
        return 0
    if old and not clone.is_ancestor(old, sha):
        warn(
            f"{name}: gate-approved ({old[:12]}) is not an ancestor of {sha[:12]}; "
            "update may refuse to fast-forward"
        )

    if args.dry_run:
        say()
        moved = f" from {old[:12]}" if old else ""
        say(f"dry run: would waive {sha[:12]} and move gate-approved{moved}; nothing written")
        return 0

    reason = args.reason
    if reason is None:
        if not verdict and not args.show:
            raise GateError(
                f"{name}: {sha[:12]} has no review verdict; read the diff with --show, "
                "or pass --reason to approve it without"
            )
        if not sys.stdin.isatty():
            raise GateError(
                "no terminal for the reason prompt; pass --reason (an empty reason is allowed)"
            )
        print("Reason (optional): ", end="", file=sys.stderr, flush=True)
        line = sys.stdin.readline()
        if not line:
            say()
            raise GateError("approval cancelled")
        reason = line.rstrip("\n")
    reason = one_line(reason)

    ctx.state.set_waiver(
        name,
        sha,
        user=ctx.cfg.user,
        reason=reason,
        base=old or "",
        patch_blob=clone.hash_object(fresh),
        evidence_blob=clone.hash_object(stored) if stored is not None and stored != fresh else "",
    )
    clone.update_ref(APPROVED_REF, sha, old)
    advance_main(clone, sha)
    ensure_hooks(ctx, name)
    ctx.state.log_event(name, f"waived {sha[:12]} by {ctx.cfg.user} reason: {reason or '<none>'}")

    say()
    say(f"Approved {sha[:12]} by hand. Run: omarchy-plugin-gate update -p {name}")
    return 0
