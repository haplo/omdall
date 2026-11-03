"""The review pipeline fails closed, whatever goes wrong."""

import dataclasses
import os
import time
from pathlib import Path

import pytest

from omdall import mechanics, proc, reviewer
from omdall.context import Context
from omdall.git import Repo
from omdall.review import review
from support import Upstream, git


@pytest.fixture
def stub_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "bin"
    d.mkdir()
    monkeypatch.setenv("PATH", f"{d}:/usr/bin:/bin")
    monkeypatch.setattr(mechanics, "validate_tree", lambda _repo, _rev: None)
    return d


def reviewer_stub(stub_bin: Path, body: str) -> None:
    p = stub_bin / "opencode"
    p.write_text(f"#!/usr/bin/env bash\n{body}\n")
    p.chmod(0o755)


ECHO_CODE = (
    'patch=""; prev=""; for a in "$@"; do [[ $prev == --file ]] && patch=$a; prev=$a; done\n'
    "code=$(tail -n 1 \"$patch\" | sed -n 's/^omdall: end of patch, code word //p')\n"
)


def candidate(upstream: Upstream) -> tuple[str, str]:
    base = git(upstream.path, "rev-parse", "HEAD")
    upstream.write("Widget.qml", "import QtQuick\nItem { width: 3 }\n")
    return base, upstream.commit()


def verdict(ctx: Context, sha: str) -> list[str]:
    return ctx.state.review_dir("demo", sha).verdict_lines()


def test_pass_runs_from_the_review_dir(ctx: Context, upstream: Upstream, stub_bin: Path) -> None:
    reviewer_stub(stub_bin, ECHO_CODE + 'pwd > cwd\necho "REVIEW PASS"\necho "SEEN $code"')
    base, new = candidate(upstream)
    assert review(ctx, "demo", upstream.repo, base, new)
    rd = ctx.state.review_dir("demo", new)
    assert (rd.path / "cwd").read_text().strip() == str(rd.path)
    assert verdict(ctx, new)[0] == "REVIEW PASS"
    assert rd.mech.read_text() == "PASS structural pre-checks\n"
    assert b"width: 3" in rd.patch.read_bytes()


def test_crash_after_pass_fails(ctx: Context, upstream: Upstream, stub_bin: Path) -> None:
    reviewer_stub(stub_bin, ECHO_CODE + 'echo "REVIEW PASS"\necho "SEEN $code"\nexit 3')
    base, new = candidate(upstream)
    assert not review(ctx, "demo", upstream.repo, base, new)
    lines = verdict(ctx, new)
    assert lines[0] == "REVIEW FAIL"
    assert "Reviewer run failed (opencode exit 3)." in lines


def test_missing_reviewer_fails(
    ctx: Context, upstream: Upstream, stub_bin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = reviewer.reviewer_argv
    monkeypatch.setattr(
        reviewer,
        "reviewer_argv",
        lambda *a: ["omdall-no-such-reviewer", *real(*a)[1:]],
    )
    base, new = candidate(upstream)
    assert not review(ctx, "demo", upstream.repo, base, new)
    assert verdict(ctx, new)[0] == "REVIEW FAIL"


def test_timeout_kills_the_process_group(
    ctx: Context, upstream: Upstream, stub_bin: Path, tmp_path: Path
) -> None:
    pidfile = tmp_path / "child.pid"
    reviewer_stub(stub_bin, f'sleep 300 &\necho $! > {pidfile}\necho "REVIEW PASS"\nsleep 300')
    quick = Context.create(dataclasses.replace(ctx.cfg, review_timeout=1))
    base, new = candidate(upstream)
    started = time.monotonic()
    assert not review(quick, "demo", upstream.repo, base, new)
    assert time.monotonic() - started < 30
    lines = verdict(quick, new)
    assert lines[0] == "REVIEW FAIL"
    assert any("timed out" in line for line in lines)
    child = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("the reviewer's background child survived the timeout")


def test_git_failure_mid_review_fails(
    ctx: Context, upstream: Upstream, stub_bin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reviewer_stub(stub_bin, ECHO_CODE + 'echo "REVIEW PASS"\necho "SEEN $code"')
    base, new = candidate(upstream)

    def broken(_self: Repo, _base: str, _new: str) -> list[object]:
        raise proc.CommandError(proc.Result(("git", "diff"), 128, b"", b"fatal: boom"))

    monkeypatch.setattr(Repo, "changes", broken)
    assert not review(ctx, "demo", upstream.repo, base, new)
    lines = verdict(ctx, new)
    assert lines[0] == "REVIEW FAIL"
    assert "fatal: boom" in lines[1]


def test_hard_failure_skips_the_model(
    ctx: Context, upstream: Upstream, stub_bin: Path, tmp_path: Path
) -> None:
    reviewer_stub(stub_bin, f"touch {tmp_path / 'invoked'}\necho 'REVIEW PASS'")
    small = Context.create(dataclasses.replace(ctx.cfg, max_patch_bytes=10))
    base, new = candidate(upstream)
    assert not review(small, "demo", upstream.repo, base, new)
    assert not (tmp_path / "invoked").exists()
    assert "byte review limit" in verdict(small, new)[1]


def test_findings_are_printed_before_the_review(
    ctx: Context,
    upstream: Upstream,
    stub_bin: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reviewer_stub(stub_bin, "exit 1")
    base = git(upstream.path, "rev-parse", "HEAD")
    upstream.write("a.desktop", "[Desktop Entry]\n")
    upstream.write("b.desktop", "[Desktop Entry]\n")
    new = upstream.commit()
    review(ctx, "demo", upstream.repo, base, new)
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "  2 structural finding(s) for the reviewer:"
    assert lines[1].startswith("    F1 ") and "a.desktop" in lines[1]
    assert lines[2].startswith("    F2 ") and "b.desktop" in lines[2]


def test_no_findings_prints_nothing(
    ctx: Context, upstream: Upstream, stub_bin: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reviewer_stub(stub_bin, "exit 1")
    base, new = candidate(upstream)
    review(ctx, "demo", upstream.repo, base, new)
    assert "structural finding" not in capsys.readouterr().out


def test_rereview_does_not_inherit_evidence(
    ctx: Context, upstream: Upstream, stub_bin: Path
) -> None:
    reviewer_stub(
        stub_bin, ECHO_CODE + 'echo "REVIEW PASS"\necho "F1 CLEARED fine"\necho "SEEN $code"'
    )
    base = git(upstream.path, "rev-parse", "HEAD")
    upstream.write("x.desktop", "[Desktop Entry]\n")
    new = upstream.commit()
    assert review(ctx, "demo", upstream.repo, base, new)
    rd = ctx.state.review_dir("demo", new)
    assert rd.cleared.is_file()
    reviewer_stub(stub_bin, "exit 1")
    assert not review(ctx, "demo", upstream.repo, base, new)
    assert not rd.cleared.exists()
