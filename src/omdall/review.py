"""A full review of one candidate: evidence, structural checks, then the model."""

from . import mechanics, reviewer
from .context import Context
from .git import Repo
from .output import info, printable
from .state import ReviewDir, write_atomic


def review(ctx: Context, name: str, clone: Repo, old: str | None, new: str) -> bool:
    """True on REVIEW PASS. Any error inside is a REVIEW FAIL, never a pass."""
    rd = ctx.state.review_dir(name, new)
    rd.reset()
    try:
        return _review(ctx, name, clone, old, new, rd)
    except Exception as e:  # noqa: BLE001 - fail closed on anything
        write_atomic(
            rd.verdict,
            f"REVIEW FAIL\nThe gate failed while reviewing: {printable(str(e))}\n",
        )
        ctx.state.log_event(name, f"gate error while reviewing {new}: {e}")
        return False


def _review(ctx: Context, name: str, clone: Repo, old: str | None, new: str, rd: ReviewDir) -> bool:
    base = old or clone.empty_tree
    patch = clone.diff(base, new)
    write_atomic(rd.patch, patch)

    mech, code_lines = mechanics.check(clone, old, new, patch, ctx.cfg.max_patch_bytes)
    write_atomic(rd.mech, mech.mech_text())
    write_atomic(rd.findings, mech.findings_text())
    if not mech.passed:
        write_atomic(rd.verdict, "".join(f"{line}\n" for line in ["REVIEW FAIL", *mech.hard]))
        ctx.state.log_event(name, f"mechanical fail for {new}")
        return False

    hints = mechanics.hints(code_lines)
    write_atomic(rd.hints, "".join(f"{h}\n" for h in hints))

    if mech.findings:
        info(f"{len(mech.findings)} structural finding(s) for the reviewer:")
        for i, text in enumerate(mech.findings, 1):
            info(f"  F{i} {text}")

    code = reviewer.new_code()
    write_atomic(rd.review_patch, reviewer.review_copy(patch, code))
    prompt = reviewer.build_prompt(
        reviewer.PromptContext(
            name=name,
            plugin_id=ctx.manifest_id(name),
            old=old,
            new=new,
            subject=clone.subject(new),
            commits=clone.log_lines(old, new, "  %h %an: %s")[:20] if old else [],
            stat=clone.diff_stat(base, new).splitlines()[-20:],
            findings=mech.findings,
            hints=hints,
        )
    )
    run = reviewer.run(ctx.cfg, rd, prompt)
    output = reviewer.clean_output(rd.review.read_bytes())
    decision = reviewer.decide(output, run.returncode, code, mech.findings, timed_out=run.timed_out)
    write_atomic(rd.verdict, decision.verdict_text())
    if decision.cleared:
        write_atomic(rd.cleared, decision.cleared_text())
    ctx.state.log_event(name, decision.log.format(sha=new))
    return decision.passed
