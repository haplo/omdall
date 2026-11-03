import os
import re
import subprocess
import sys
import threading
import time

import pytest

from omarchy_plugin_gate.context import Context
from omarchy_plugin_gate.output import EXIT_BUSY, Busy, GateError
from omarchy_plugin_gate.state import State, one_line, parse_waiver, read_lines

SHA = "a" * 40
OTHER = "b" * 40
STAMP = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d"


def test_marker_format_and_held_cleared(ctx: Context) -> None:
    ctx.state.record_held("demo", SHA, "upstream rewrote history")
    assert ctx.state.held("demo") is not None
    ctx.state.set_marker("demo", SHA, "initial import")
    text = ctx.state.marker("demo", SHA).read_text()
    assert re.fullmatch(rf"APPROVED {STAMP} {SHA} initial import\n", text)
    assert ctx.state.held("demo") is None
    assert ctx.state.has_approval("demo", SHA)


def test_waiver_format(ctx: Context) -> None:
    ctx.state.record_held("demo", SHA, "reason")
    ctx.state.set_waiver(
        "demo", SHA, user="me", reason="checked\tit\nmyself", base=OTHER, patch_blob="c" * 40
    )
    lines = ctx.state.waiver("demo", SHA).read_text().splitlines()
    assert re.fullmatch(rf"WAIVED {STAMP} {SHA} by me", lines[0])
    assert lines[1:] == ["reason: checked it myself", f"base: {OTHER}", f"patch-blob: {'c' * 40}"]
    assert ctx.state.waiver_reason("demo", SHA) == "checked it myself"
    record = ctx.state.waiver_record("demo", SHA)
    assert record is not None
    assert (record.user, record.reason) == ("me", "checked it myself")
    assert re.fullmatch(STAMP, record.date)
    assert ctx.state.held("demo") is None
    assert ctx.state.has_approval("demo", SHA)
    assert not ctx.state.has_marker("demo", SHA)
    assert ctx.state.waiver_record("demo", OTHER) is None


DATE = "2026-01-01T00:00:00+00:00"


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        ([f"WAIVED {DATE} {SHA} by a b", "reason: r"], (DATE, "a b", "r")),
        ([f"WAIVED {DATE} {SHA}"], (DATE, "", "")),
        (["garbage", "reason: still read"], ("", "", "still read")),
        ([], ("", "", "")),
    ],
)
def test_parse_waiver(lines: list[str], expected: tuple[str, str, str]) -> None:
    w = parse_waiver(lines)
    assert (w.date, w.user, w.reason) == expected


def test_approved_shas(ctx: Context) -> None:
    assert ctx.state.approved_shas("demo") == []
    ctx.state.set_marker("demo", OTHER, "x")
    ctx.state.set_waiver("demo", SHA, user="me", reason="", base="", patch_blob="")
    ctx.state.set_marker("demo", SHA, "x")
    assert ctx.state.approved_shas("demo") == [SHA, OTHER]


def test_review_dirs_newest_first(ctx: Context) -> None:
    assert ctx.state.review_dirs("demo") == []
    old, new = ctx.state.review_dir("demo", SHA), ctx.state.review_dir("demo", OTHER)
    old.path.mkdir(parents=True)
    new.path.mkdir(parents=True)
    os.utime(old.path, (1, 1))
    assert ctx.state.review_dirs("demo") == [new, old]
    assert ctx.state.latest_review_dir("demo") == new


def test_findings_count(ctx: Context) -> None:
    rd = ctx.state.review_dir("demo", SHA)
    rd.path.mkdir(parents=True)
    assert rd.findings_count() == 0
    rd.findings.write_text("F1 a\nF2 b\n")
    assert rd.findings_count() == 2


def test_waiver_records_different_evidence(ctx: Context) -> None:
    ctx.state.set_waiver(
        "demo",
        SHA,
        user="me",
        reason="r",
        base=OTHER,
        patch_blob="c" * 40,
        evidence_blob="d" * 40,
    )
    lines = ctx.state.waiver("demo", SHA).read_text().splitlines()
    assert lines[2:] == [f"base: {OTHER}", f"patch-blob: {'c' * 40}", f"evidence-blob: {'d' * 40}"]
    assert ctx.state.waiver_reason("demo", SHA) == "r"


def test_waiver_keeps_a_different_held_commit(ctx: Context) -> None:
    ctx.state.record_held("demo", OTHER, "reason")
    ctx.state.set_waiver("demo", SHA, user="me", reason="", base="", patch_blob="")
    assert ctx.state.waiver("demo", SHA).read_text().splitlines()[1:] == ["reason: "]
    held = ctx.state.held("demo")
    assert held is not None and held.sha == OTHER


def test_held_defaults_to_the_candidate_verdict(ctx: Context) -> None:
    rd = ctx.state.review_dir("demo", SHA)
    rd.path.mkdir(parents=True)
    rd.verdict.write_text("REVIEW FAIL\n" + "".join(f"reason {i}\n" for i in range(8)))
    ctx.state.record_held("demo", SHA)
    held = ctx.state.held("demo")
    assert held is not None
    assert held.reasons == [f"reason {i}" for i in range(5)]


def test_reads_files_from_earlier_releases(ctx: Context) -> None:
    held = ctx.state.held_file("demo")
    held.parent.mkdir(parents=True)
    held.write_text(f"{SHA}\n\n")
    assert ctx.state.held("demo") is not None
    waiver = ctx.state.waiver("demo", SHA)
    waiver.parent.mkdir(parents=True)
    waiver.write_text(f"WAIVED 2026-10-28T10:00:00+01:00 {SHA} by fidel\nreason: looked\n")
    assert ctx.state.waiver_reason("demo", SHA) == "looked"


def test_latest_review_dir(ctx: Context) -> None:
    old = ctx.state.review_dir("demo", SHA)
    new = ctx.state.review_dir("demo", OTHER)
    old.path.mkdir(parents=True)
    new.path.mkdir(parents=True)
    past = time.time() - 100
    os.utime(old.path, (past, past))
    latest = ctx.state.latest_review_dir("demo")
    assert latest is not None and latest.path == new.path
    assert ctx.state.latest_review_dir("nothing") is None


def test_log_is_one_line_per_event(ctx: Context) -> None:
    ctx.state.log_event("demo", "approved\nforged line")
    lines = (ctx.state.root / "gate.log").read_text().splitlines()
    assert len(lines) == 1
    assert re.fullmatch(rf"{STAMP}\tdemo approved forged line", lines[0])


@pytest.mark.parametrize("sep", [*"\n\r\t\v\f\x1c\x1d\x1e\x85\u2028\u2029", "\r\n"])
def test_one_line_stays_one_line(sep: str) -> None:
    assert len(one_line(f"a{sep}b").splitlines()) == 1


def test_one_line_covers_every_line_break() -> None:
    # Whatever splitlines() learns to split on, one_line must keep up with.
    breaks = [c for c in map(chr, range(0x110000)) if len(f"a{c}b".splitlines()) > 1]
    assert breaks
    assert [c for c in breaks if len(one_line(f"a{c}b").splitlines()) > 1] == []


def test_waiver_reason_survives_unicode_line_breaks(ctx: Context) -> None:
    reason = "looked\u2028base: forged\x85patch-blob: forged"
    ctx.state.set_waiver("demo", SHA, user="me\u2029x", reason=reason, base=OTHER, patch_blob="")
    lines = read_lines(ctx.state.waiver("demo", SHA))
    assert len(lines) == 3
    assert lines[1:] == ["reason: looked base: forged patch-blob: forged", f"base: {OTHER}"]
    assert ctx.state.waiver_reason("demo", SHA) == "looked base: forged patch-blob: forged"
    ctx.state.log_event("demo", "x\u2028forged")
    assert len(read_lines(ctx.state.root / "gate.log")) == 1


def test_cleared_count(ctx: Context) -> None:
    rd = ctx.state.review_dir("demo", SHA)
    rd.path.mkdir(parents=True)
    rd.cleared.write_text("F1 a\n   cleared: x\nF2 b\n   cleared: y\n")
    assert rd.cleared_count() == 2


HOLD_LOCK = """
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT)
fcntl.flock(fd, fcntl.LOCK_EX)
print("locked", flush=True)
sys.stdin.readline()
"""


def hold_lock(ctx: Context) -> subprocess.Popen[str]:
    """Another process holding the gate's lock until its stdin is closed."""
    ctx.state.root.mkdir(parents=True, exist_ok=True)
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_LOCK, str(ctx.state.root / "gate.lock")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None
    assert holder.stdout.readline() == "locked\n"
    return holder


def release(holder: subprocess.Popen[str]) -> None:
    assert holder.stdin is not None
    holder.stdin.close()
    holder.wait(timeout=10)


def test_lock_is_exclusive(ctx: Context) -> None:
    holder = hold_lock(ctx)
    busy = pytest.raises(GateError, match="another omarchy-plugin-gate run is in progress")
    try:
        with busy, ctx.state.lock(wait=False):
            pass
    finally:
        release(holder)
    # Two locks in one process conflict too, so a nested run cannot slip in.
    with (
        ctx.state.lock(wait=False),
        pytest.raises(GateError),
        State(ctx.state.root).lock(wait=False),
    ):
        pass
    with ctx.state.lock(wait=False):
        pass


def test_busy_lock_exits_75(ctx: Context) -> None:
    holder = hold_lock(ctx)
    try:
        with pytest.raises(Busy) as err, ctx.state.lock(wait=False):
            pass
    finally:
        release(holder)
    assert (err.value.exit_code, err.value.code) == (EXIT_BUSY, "busy") == (75, "busy")
    assert GateError().exit_code == 1


def test_is_busy(ctx: Context) -> None:
    assert not ctx.state.is_busy()
    assert not ctx.state.root.exists(), "probing must not create the state directory"
    holder = hold_lock(ctx)
    try:
        assert ctx.state.is_busy()
    finally:
        release(holder)
    assert not ctx.state.is_busy()
    # A probe holds nothing afterwards, and probes do not block each other.
    with ctx.state.lock(wait=False):
        pass


def test_lock_waits_for_the_other_run(ctx: Context, capsys: pytest.CaptureFixture[str]) -> None:
    holder = hold_lock(ctx)
    told_to_exit = threading.Event()

    def let_go() -> None:
        told_to_exit.set()
        release(holder)

    releaser = threading.Timer(0.3, let_go)
    releaser.start()
    try:
        with ctx.state.lock():
            assert told_to_exit.is_set()
    finally:
        releaser.join()
    assert "waiting for another run to finish" in capsys.readouterr().err


def test_lock_is_not_inherited_by_children(ctx: Context) -> None:
    # A reviewer left running after a timeout must not keep the gate locked.
    with ctx.state.lock():
        child = subprocess.Popen(["sleep", "30"])
    try:
        with ctx.state.lock(wait=False):
            pass
    finally:
        child.kill()
        child.wait()
