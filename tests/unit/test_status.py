"""status --json, reviews, --no-wait: the contract a UI reads."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from omdall import __version__, cli, proc
from omdall.commands import reviews, status
from omdall.config import APPROVED_REF
from omdall.context import Context
from omdall.output import EXIT_BUSY
from omdall.plugins import public_url
from support import Upstream, git
from test_state import hold_lock, release

LAUNCHER = Path(__file__).parents[2] / "bin" / "omdall"


@pytest.fixture
def demo(ctx: Context, upstream: Upstream) -> tuple[str, str]:
    """A gate clone with the initial import approved and a later commit held."""
    first = git(upstream.path, "rev-parse", "HEAD")
    upstream.write("Widget.qml", "import QtQuick\nItem { \x1b[2J }\n")
    held = upstream.commit("second\x1b]52;c;x\x07")
    clone = ctx.clone_dir("demo")
    git(upstream.path.parent, "clone", "-q", str(upstream.path), str(clone))
    git(clone, "update-ref", APPROVED_REF, first)
    ctx.state.set_marker("demo", first, "initial import")
    for sha, verdict in ((first, "REVIEW PASS\n"), (held, "REVIEW FAIL\nbad \x1b[1m thing\n")):
        rd = ctx.state.review_dir("demo", sha)
        rd.path.mkdir(parents=True, exist_ok=True)
        (rd.patch).write_text("diff\n")
        rd.verdict.write_text(verdict)
    ctx.state.record_held("demo", held)
    return first, held


def read_json(capsys: pytest.CaptureFixture[str]) -> dict:
    out = capsys.readouterr().out
    return json.loads(out)


def test_status_json(
    ctx: Context, demo: tuple[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    first, held = demo
    assert status.run(ctx, "", as_json=True) == 0
    data = read_json(capsys)
    assert data["schema"] == 1
    assert data["version"] == __version__
    assert data["busy"] is False
    assert (data["root"], data["state"]) == (str(ctx.cfg.root), str(ctx.state.root))
    [p] = data["plugins"]
    assert (p["name"], p["id"], p["state"], p["next"]) == (
        "demo",
        "selftest.demo",
        "held back",
        "approve",
    )
    assert (p["approved"], p["upstream"], p["installed"]) == (first, held, None)
    assert p["held"] == {
        "sha": held,
        "reasons": ["bad \\x1b[1m thing"],
        "subject": "second\\x1b]52;c;x\\x07",
        "author": "gate test",
    }
    assert (p["pending"], p["update_blocked"]) == (1, "not_installed")
    assert p["upstream_url"] == str(ctx.clone_dir("demo").parent.parent / "upstream")
    assert data["features"] == ["activity", "action-json", "attention"]
    assert data["attention"] == [{"name": "demo", "why": "held"}]
    assert data["activity"] is None
    assert p["waiver"] is None
    latest = p["latest_review"]
    assert latest["sha"] == held
    assert latest["verdict"] == "REVIEW FAIL"
    assert latest["passed"] is False
    assert latest["subject"] == "second\\x1b]52;c;x\\x07"
    assert latest["approval"] is None
    assert set(latest["files"]) == {"patch", "verdict"}


def test_status_json_reports_busy(
    ctx: Context, demo: tuple[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    holder = hold_lock(ctx)
    try:
        status.run(ctx, "", as_json=True)
    finally:
        release(holder)
    assert read_json(capsys)["busy"] is True


def test_status_text_unchanged(
    ctx: Context, demo: tuple[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    _first, held = demo
    status.run(ctx, "")
    out = capsys.readouterr().out
    assert "state     held back" in out
    assert "next      omdall approve -p demo" in out
    assert "last review: REVIEW FAIL" in out
    assert f"patch: {ctx.state.review_dir('demo', held).patch}" in out
    assert "\x1b" not in out


def test_reviews_json(
    ctx: Context, demo: tuple[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    first, held = demo
    assert reviews.run(ctx, "selftest.demo", as_json=True) == 0
    data = read_json(capsys)
    [p] = data["plugins"]
    assert (p["name"], p["id"]) == ("demo", "selftest.demo")
    shas = [r["sha"] for r in p["reviews"]]
    assert set(shas) == {first, held}
    by_sha = {r["sha"]: r for r in p["reviews"]}
    assert by_sha[first]["approval"] == "reviewed"
    assert by_sha[first]["passed"] is True
    assert by_sha[held]["reasons"] == ["bad \\x1b[1m thing"]
    assert by_sha[held]["short"] == held[:12]


def test_reviews_text(
    ctx: Context, demo: tuple[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    reviews.run(ctx, "demo")
    out = capsys.readouterr().out
    assert "approved by review" in out
    assert "bad \\x1b[1m thing" in out
    assert "\x1b" not in out


def test_full_sha(upstream: Upstream) -> None:
    head = git(upstream.path, "rev-parse", "HEAD")
    other = "f" * 40
    assert reviews.full_sha(other[:12], [other], upstream.repo) == other
    assert reviews.full_sha(head[:12], [], upstream.repo) == head
    assert reviews.full_sha("not-a-sha", [], upstream.repo) is None
    assert reviews.full_sha("--all", [], upstream.repo) is None


def test_json_error_on_stdout(ctx: Context, capsys: pytest.CaptureFixture[str]) -> None:
    ctx.cfg.root.mkdir(parents=True)
    env_args = ["--root", str(ctx.cfg.root), "--state", str(ctx.state.root)]
    assert cli.main(LAUNCHER, [*env_args, "status", "-p", "missing", "--json"]) == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["schema"] == 1
    assert data["code"] == "not_found"
    assert "no plugin named 'missing'" in data["error"]
    assert captured.err.startswith("omdall: no plugin named")


def test_reviews_name_and_plugin_conflict(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    argv = ["--root", str(tmp_path), "reviews", "a", "-p", "b"]
    assert cli.main(LAUNCHER, argv) == 1
    assert "unexpected argument: a" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["check"],
        ["update"],
        ["doctor", "--fix"],
        ["approve", "demo", "--reason", "x"],
        ["add", "/x"],
    ],
)
def test_no_wait_exits_75(
    ctx: Context, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    holder = hold_lock(ctx)
    try:
        args = ["--root", str(ctx.cfg.root), "--state", str(ctx.state.root), *argv, "--no-wait"]
        assert cli.main(LAUNCHER, args) == EXIT_BUSY
    finally:
        release(holder)
    err = capsys.readouterr().err
    assert "another omdall run is in progress" in err
    assert "waiting" not in err


@pytest.mark.parametrize("argv", [["approve", "demo", "-n"], ["doctor"]])
def test_no_wait_is_harmless_where_nothing_waits(
    ctx: Context,
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(proc, "which", lambda _name: None)
    holder = hold_lock(ctx)
    try:
        args = ["--root", str(ctx.cfg.root), "--state", str(ctx.state.root), *argv, "--no-wait"]
        assert cli.main(LAUNCHER, args) != EXIT_BUSY
    finally:
        release(holder)
    assert "in progress" not in capsys.readouterr().err


@pytest.mark.parametrize("command", ["check", "update", "doctor"])
def test_action_json_keeps_stdout_for_the_object(
    ctx: Context,
    command: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx.cfg.root.mkdir(parents=True)
    monkeypatch.setattr(proc, "which", lambda _name: None)
    args = ["--root", str(ctx.cfg.root), "--state", str(ctx.state.root), command, "--json"]
    code = cli.main(LAUNCHER, args)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert (data["schema"], data["command"], data["ok"]) == (1, command, code == 0)
    assert data["results"] == [] or command == "doctor"
    assert captured.err


def test_action_json_busy(ctx: Context, capsys: pytest.CaptureFixture[str]) -> None:
    holder = hold_lock(ctx)
    try:
        args = ["--root", str(ctx.cfg.root), "--state", str(ctx.state.root)]
        assert cli.main(LAUNCHER, [*args, "check", "--no-wait", "--json"]) == EXIT_BUSY
    finally:
        release(holder)
    assert json.loads(capsys.readouterr().out)["code"] == "busy"


CLEAN = status.PluginRecord(
    name="",
    id=None,
    clone="",
    installed_dir=None,
    branch="main",
    approved="a",
    installed="a",
    upstream="a",
    state="installed",
    next=None,
    dirty=[],
    never_reviewed=False,
    waiver=None,
    cleared=0,
    cleared_file=None,
    held=None,
    latest_review=None,
    pending=0,
    update_blocked=None,
    upstream_url=None,
)


def record(name: str, **changes: Any) -> status.PluginRecord:
    return replace(CLEAN, name=name, **changes)


def test_attention_order_and_reasons() -> None:
    records = [
        record("clean"),
        record("edited", dirty=["x"]),
        record("ready", state="ready to install", dirty=["x"]),
        record("absent", state="approved, not installed"),
        record("local", never_reviewed=True, state="ready to install"),
        record("held", state="held back", never_reviewed=True),
        record("fresh", state="not reviewed yet"),
    ]
    assert [(a.name, a.why) for a in status.attention(records)] == [
        ("held", "held"),
        ("local", "never_reviewed"),
        ("absent", "ready"),
        ("ready", "ready"),
        ("edited", "dirty"),
    ]


@pytest.mark.parametrize(
    ("approved", "approved_ok", "installed", "exists", "dirty", "blocked"),
    [
        (None, False, None, False, False, "no_approval"),
        ("a", False, "b", True, False, "no_approval"),
        ("a", True, None, False, False, "not_installed"),
        ("a", True, "a", True, True, None),
        ("a", True, "b", True, True, "dirty"),
        ("a", True, "b", True, False, None),
    ],
)
def test_update_blocked(
    approved: str | None,
    approved_ok: bool,
    installed: str | None,
    exists: bool,
    dirty: bool,
    blocked: str | None,
) -> None:
    assert status.update_blocked(approved, approved_ok, installed, exists, dirty) == blocked


@pytest.mark.parametrize(
    ("url", "shown"),
    [
        ("https://user:tok@en@github.com/a/b", "https://github.com/a/b"),
        ("https://github.com/a/b", "https://github.com/a/b"),
        ("ssh://git@host/x", "ssh://host/x"),
        ("git@github.com:a/b", "git@github.com:a/b"),
        ("/srv/git/x", "/srv/git/x"),
    ],
)
def test_public_url(url: str, shown: str) -> None:
    assert public_url(url) == shown


def test_status_activity_only_shows_a_run_holding_the_lock(
    ctx: Context, demo: tuple[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    ctx.activity.start("check")
    ctx.activity.running = None  # a crashed run: the file says running, the lock is free
    status.run(ctx, "", as_json=True)
    data = read_json(capsys)
    assert data["activity"]["seq"] == 1
    assert data["activity"]["running"] is None
    holder = hold_lock(ctx)
    try:
        status.run(ctx, "", as_json=True)
    finally:
        release(holder)
    assert read_json(capsys)["activity"]["running"]["command"] == "check"
