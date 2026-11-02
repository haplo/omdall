"""How the tripwire finds its plugin: from the hook and the approved commit,
never from the merged files, and never through an invalid id."""

from pathlib import Path

import pytest

from omarchy_plugin_gate.commands import post_merge, update
from omarchy_plugin_gate.config import APPROVED_REF
from omarchy_plugin_gate.context import Context
from omarchy_plugin_gate.git import Repo
from omarchy_plugin_gate.plugins import approved_manifest_id, manifest_id_of
from support import Upstream, git


@pytest.fixture
def wired(
    ctx: Context, upstream: Upstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[str], list[str]]:
    """A gate clone `demo` with gate-approved at its HEAD, an installed copy that
    tracks it, and records of what the tripwire reviewed and disabled."""
    ctx.cfg.root.mkdir(parents=True)
    clone = ctx.clone_dir("demo")
    git(tmp_path, "clone", "-q", str(upstream.path), str(clone))
    git(clone, "update-ref", APPROVED_REF, "HEAD")
    idir = ctx.cfg.installed_root / "selftest.demo"
    git(tmp_path, "clone", "-q", str(clone), str(idir))

    reviewed: list[str] = []
    disabled: list[str] = []

    def review(_ctx: Context, name: str, _clone: object, old: str, new: str) -> bool:
        reviewed.append(f"{name} {old}..{new}")
        return False

    monkeypatch.setattr(post_merge, "review", review)
    monkeypatch.setattr(post_merge, "disable_plugin", disabled.append)
    monkeypatch.setattr(post_merge, "notify", lambda *_args: None)
    return idir, reviewed, disabled


def change_id_upstream(ctx: Context, upstream: Upstream) -> str:
    upstream.manifest(id="selftest.other")
    new = upstream.commit("change the id")
    git(ctx.clone_dir("demo"), "fetch", "-q")
    return new


def test_approved_manifest_id_ignores_the_working_tree(ctx: Context, upstream: Upstream) -> None:
    ctx.cfg.root.mkdir(parents=True)
    clone = ctx.clone_dir("demo")
    git(clone.parent, "clone", "-q", str(upstream.path), str(clone))
    assert approved_manifest_id(ctx.clone("demo")) == ""
    git(clone, "update-ref", APPROVED_REF, "HEAD")
    (clone / "manifest.json").write_text('{"id": "selftest.other"}')
    assert approved_manifest_id(ctx.clone("demo")) == "selftest.demo"


@pytest.mark.parametrize("bad", ["../x", "/etc", "omarchy.core", "a/b", ""])
def test_no_path_is_built_from_an_invalid_id(ctx: Context, upstream: Upstream, bad: str) -> None:
    assert manifest_id_of({"id": bad}) == ""
    ctx.cfg.root.mkdir(parents=True)
    clone = ctx.clone_dir("demo")
    upstream.manifest(id=bad)
    upstream.commit()
    git(clone.parent, "clone", "-q", str(upstream.path), str(clone))
    git(clone, "update-ref", APPROVED_REF, "HEAD")
    assert approved_manifest_id(ctx.clone("demo")) == ""
    assert ctx.manifest_id("demo") == ""
    assert ctx.installed_dir("demo") is None


def test_installed_copy_that_changes_its_id_is_reviewed_and_rolled_back(
    ctx: Context, upstream: Upstream, wired: tuple[Path, list[str], list[str]]
) -> None:
    idir, reviewed, disabled = wired
    old = git(idir, "rev-parse", "HEAD")
    new = change_id_upstream(ctx, upstream)
    git(idir, "pull", "-q", "--ff-only", "origin", "refs/remotes/origin/main")
    assert git(idir, "rev-parse", "HEAD") == new

    assert post_merge.run(ctx, "demo", str(idir)) == 1
    assert reviewed == [f"demo {old}..{new}"]
    assert git(idir, "rev-parse", "HEAD") == old
    assert disabled == ["selftest.demo"]


def test_clone_rollback_does_not_disable(
    ctx: Context, upstream: Upstream, wired: tuple[Path, list[str], list[str]]
) -> None:
    _idir, reviewed, disabled = wired
    clone = ctx.clone_dir("demo")
    old = git(clone, "rev-parse", "HEAD")
    new = change_id_upstream(ctx, upstream)
    git(clone, "merge", "-q", "--ff-only", "origin/main")

    assert post_merge.run(ctx, "demo", str(clone)) == 1
    assert reviewed == [f"demo {old}..{new}"]
    assert git(clone, "rev-parse", "HEAD") == old
    assert disabled == []


def test_rollback_keeps_uncommitted_work(
    ctx: Context, upstream: Upstream, wired: tuple[Path, list[str], list[str]]
) -> None:
    _idir, _reviewed, _disabled = wired
    clone = ctx.clone_dir("demo")
    old = git(clone, "rev-parse", "HEAD")
    change_id_upstream(ctx, upstream)
    (clone / "Widget.qml").write_text("// my edit\n")
    (clone / "notes.txt").write_text("untracked\n")
    git(clone, "merge", "-q", "--ff-only", "origin/main")

    assert post_merge.run(ctx, "demo", str(clone)) == 1
    assert git(clone, "rev-parse", "HEAD") == old
    assert (clone / "Widget.qml").read_text() == "// my edit\n"
    assert (clone / "notes.txt").read_text() == "untracked\n"


@pytest.mark.parametrize("where", ["clone", "installed"])
def test_rollback_never_discards_local_changes(
    ctx: Context,
    upstream: Upstream,
    wired: tuple[Path, list[str], list[str]],
    monkeypatch: pytest.MonkeyPatch,
    where: str,
) -> None:
    idir, reviewed, disabled = wired
    target = ctx.clone_dir("demo") if where == "clone" else idir
    notes: list[str] = []
    monkeypatch.setattr(
        post_merge, "notify", lambda _ctx, head, body: notes.append(f"{head}|{body}")
    )
    old = git(target, "rev-parse", "HEAD")
    new = change_id_upstream(ctx, upstream)
    if where == "installed":
        git(target, "fetch", "-q", "origin", "refs/remotes/origin/main")
        git(target, "merge", "-q", "--ff-only", "FETCH_HEAD")
    else:
        git(target, "merge", "-q", "--ff-only", "origin/main")
    # Edited after the merge, in a file the merge changed: going back to `old`
    # would overwrite it.
    (target / "manifest.json").write_text("{}\n")

    assert post_merge.run(ctx, "demo", str(target)) == 1
    assert reviewed == [f"demo {old}..{new}"]
    assert git(target, "rev-parse", "HEAD") == new
    assert (target / "manifest.json").read_text() == "{}\n"
    assert disabled == (["selftest.demo"] if where == "installed" else [])
    log = (ctx.state.root / "gate.log").read_text()
    assert f"hook: could not roll back {new} without discarding local changes" in log
    assert "hook: rolled back" not in log
    (note,) = notes
    assert note.startswith("demo: rollback failed|")
    assert "discarding local changes" in note


def test_update_rollback_never_discards_local_changes(
    ctx: Context,
    upstream: Upstream,
    wired: tuple[Path, list[str], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    idir, _reviewed, _disabled = wired
    disabled: list[str] = []
    notes: list[str] = []
    monkeypatch.setattr(update, "disable_plugin", disabled.append)
    monkeypatch.setattr(update, "notify", lambda _ctx, head, _body: notes.append(head))
    old = git(idir, "rev-parse", "HEAD")
    new = change_id_upstream(ctx, upstream)
    git(idir, "fetch", "-q", "origin", "refs/remotes/origin/main")
    git(idir, "merge", "-q", "--ff-only", "FETCH_HEAD")

    (idir / "manifest.json").write_text("{}\n")
    assert not update._roll_back(ctx, "demo", Repo(idir), old)
    assert git(idir, "rev-parse", "HEAD") == new
    assert (idir / "manifest.json").read_text() == "{}\n"
    assert disabled == ["selftest.demo"]
    assert notes == ["demo: rollback failed"]

    git(idir, "checkout", "-q", "--", "manifest.json")
    (idir / "notes.txt").write_text("untracked\n")
    assert update._roll_back(ctx, "demo", Repo(idir), old)
    assert git(idir, "rev-parse", "HEAD") == old
    assert (idir / "notes.txt").read_text() == "untracked\n"
    assert notes == ["demo: rollback failed"]


@pytest.mark.parametrize("name", ["nothing", "", "../demo"])
def test_unknown_plugin_is_left_alone(
    ctx: Context, upstream: Upstream, wired: tuple[Path, list[str], list[str]], name: str
) -> None:
    idir, reviewed, _disabled = wired
    new = change_id_upstream(ctx, upstream)
    git(idir, "pull", "-q", "--ff-only", "origin", "refs/remotes/origin/main")
    assert post_merge.run(ctx, name, str(idir)) == 0
    assert reviewed == []
    assert git(idir, "rev-parse", "HEAD") == new


def test_directory_of_another_plugin_is_left_alone(
    ctx: Context,
    upstream: Upstream,
    wired: tuple[Path, list[str], list[str]],
    tmp_path: Path,
) -> None:
    _idir, reviewed, _disabled = wired
    stray = tmp_path / "stray"
    git(tmp_path, "clone", "-q", str(ctx.clone_dir("demo")), str(stray))
    upstream.write("Widget.qml", "import QtQuick\nItem { width: 3 }\n")
    upstream.commit()
    git(ctx.clone_dir("demo"), "fetch", "-q")
    git(stray, "pull", "-q", "--ff-only", "origin", "refs/remotes/origin/main")

    assert post_merge.run(ctx, "demo", str(stray)) == 0
    assert reviewed == []
    log = (ctx.state.root / "gate.log").read_text()
    assert f"hook: {stray} is neither the clone nor the installed copy" in log
