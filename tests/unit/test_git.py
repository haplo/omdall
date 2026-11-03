from pathlib import Path

import pytest

from omdall import proc
from omdall.commands import advance_main
from omdall.git import Repo, parse_numstat_z, parse_raw_z, parse_status_z
from support import Upstream, git

Z40 = "0" * 40
B40 = "b" * 40


def test_parse_raw_z_plain_and_rename() -> None:
    data = (
        f":000000 100755 {Z40} {B40} A\0new tool\0".encode()
        + f":100644 100644 {B40} {B40} R087\0old.qml\0.ssh/x\0".encode()
    )
    assert parse_raw_z(data) == [
        ("A", "new tool", "000000", "100755", B40, None),
        ("R", ".ssh/x", "100644", "100644", B40, "old.qml"),
    ]


def test_parse_raw_z_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="unexpected raw diff record"):
        parse_raw_z(b"garbage\0")


def test_parse_numstat_z() -> None:
    data = b"1\t0\ta\tb.qml\0-\t-\tpayload.bin\0" + b"2\t1\t\0old.qml\0new.qml\0"
    assert parse_numstat_z(data) == {"a\tb.qml": False, "payload.bin": True, "new.qml": False}


def test_parse_status_z() -> None:
    data = b" M Widget.qml\0R  new.qml\0old.qml\0?? line\nbreak\0!! cache/x\0"
    assert parse_status_z(data) == [
        (" M", "Widget.qml"),
        ("R ", "new.qml"),
        ("??", "line\nbreak"),
        ("!!", "cache/x"),
    ]


def test_parse_status_z_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="unexpected status record"):
        parse_status_z(b"garbage\0")


def test_dirty_and_ignored_paths(upstream: Upstream) -> None:
    repo = upstream.repo
    assert repo.dirty_paths() == []
    assert repo.ignored_paths() == []
    (upstream.path / ".git" / "info").mkdir(exist_ok=True)
    (upstream.path / ".git" / "info" / "exclude").write_text("cache/\n")
    upstream.write("cache/deep/x", "x")
    assert repo.dirty_paths() == []
    assert repo.ignored_paths() == ["cache/deep/x"]
    upstream.write("Widget.qml", "import QtQuick\nItem {}\n// changed\n")
    upstream.write("new dir/extra.qml", "x\n")
    assert sorted(repo.dirty_paths()) == ["Widget.qml", "new dir/extra.qml"]
    git(upstream.path, "add", "-A")
    git(upstream.path, "mv", "Widget.qml", "Moved.qml")
    assert sorted(repo.dirty_paths()) == ["Moved.qml", "new dir/extra.qml"]


def test_parse_keeps_undecodable_bytes() -> None:
    data = f":000000 100644 {Z40} {B40} A\0".encode() + b"caf\xe9.qml\0"
    (_, path, *_rest) = parse_raw_z(data)[0]
    assert path.encode("utf-8", "surrogateescape") == b"caf\xe9.qml"


def test_changes_with_awkward_paths(upstream: Upstream) -> None:
    base = git(upstream.path, "rev-parse", "HEAD")
    upstream.write("line\nbreak.desktop", "x\n")
    upstream.write("tab\there.qml", "x\n")
    upstream.write("caf\u00e9 \u2603.qml", "x\n")
    upstream.write(b"raw\xff.qml", "x\n")
    upstream.write("tool", "payload\n", mode=0o755)
    upstream.write("payload.bin", b"a\0b\0c\0")
    new = upstream.commit("awkward")
    changes = {c.path: c for c in upstream.repo.changes(base, new)}
    assert set(changes) >= {
        "line\nbreak.desktop",
        "tab\there.qml",
        "caf\u00e9 \u2603.qml",
        "raw\udcff.qml",
        "tool",
        "payload.bin",
    }
    assert changes["tool"].became_executable
    assert not changes["tool"].binary
    assert changes["payload.bin"].binary


def test_rename_reports_destination(upstream: Upstream) -> None:
    base = git(upstream.path, "rev-parse", "HEAD")
    git(upstream.path, "mv", "Widget.qml", "authorized_keys")
    new = upstream.commit("rename")
    (change,) = upstream.repo.changes(base, new)
    assert change.status == "R"
    assert change.path == "authorized_keys"
    assert change.old_path == "Widget.qml"


def test_mode_change_counts_as_becoming_executable(upstream: Upstream) -> None:
    base = git(upstream.path, "rev-parse", "HEAD")
    (upstream.path / "Widget.qml").chmod(0o755)
    new = upstream.commit("chmod")
    (change,) = upstream.repo.changes(base, new)
    assert change.became_executable


def test_gitattributes_cannot_hide_code(upstream: Upstream) -> None:
    # A plugin's .gitattributes must not turn its code into "Binary files differ".
    upstream.write(".gitattributes", "*.qml -diff\n")
    base = upstream.commit("attributes")
    upstream.write("Widget.qml", "import QtQuick\nItem { Component.onCompleted: evil() }\n")
    new = upstream.commit("hidden change")
    patch = upstream.repo.diff(base, new)
    assert b"evil()" in patch
    (change,) = upstream.repo.changes(base, new)
    assert not change.binary


def test_user_config_does_not_change_the_patch(upstream: Upstream, tmp_path: Path) -> None:
    base = git(upstream.path, "rev-parse", "HEAD")
    upstream.write("Widget.qml", "import QtQuick\nItem { width: 1 }\n")
    new = upstream.commit("edit")
    git(upstream.path, "config", "color.ui", "always")
    git(upstream.path, "config", "diff.noprefix", "true")
    patch = upstream.repo.diff(base, new)
    assert b"\x1b[" not in patch
    assert b"diff --git a/Widget.qml b/Widget.qml" in patch


def test_tree_paths_lists_every_file(upstream: Upstream) -> None:
    upstream.write("sub/deep/.gitattributes", "x\n")
    upstream.write("line\nbreak", "x\n")
    new = upstream.commit()
    assert sorted(upstream.repo.tree_paths(new)) == [
        "Widget.qml",
        "line\nbreak",
        "manifest.json",
        "sub/deep/.gitattributes",
    ]


def test_blob_sizes(upstream: Upstream) -> None:
    upstream.write("five", "12345")
    new = upstream.commit()
    blob = git(upstream.path, "rev-parse", f"{new}:five")
    sizes = upstream.repo.blob_sizes([blob, blob, new, Z40])
    assert sizes == {blob: 5}
    assert upstream.repo.blob_sizes([]) == {}


def test_advance_main_does_not_run_filters(upstream: Upstream, tmp_path: Path) -> None:
    clones = [tmp_path / "gate", tmp_path / "plain"]
    for clone in clones:
        git(tmp_path, "clone", "-q", str(upstream.path), str(clone))
        git(clone, "config", "filter.evil.smudge", "sed s/reviewed/SMUDGED/")
        git(clone, "config", "filter.evil.clean", "cat")
    upstream.write(".gitattributes", "*.qml filter=evil\n")
    upstream.write("Widget.qml", "reviewed\n")
    new = upstream.commit()
    for clone in clones:
        git(clone, "fetch", "-q")

    advance_main(Repo(clones[0]), new)
    assert git(clones[0], "rev-parse", "HEAD") == new
    assert (clones[0] / "Widget.qml").read_text() == "reviewed\n"
    # The same merge without the gate's protection runs the filter.
    git(clones[1], "merge", "-q", "--ff-only", new)
    assert (clones[1] / "Widget.qml").read_text() == "SMUDGED\n"


def test_update_ref_checks_the_old_value(upstream: Upstream) -> None:
    repo = upstream.repo
    first = git(upstream.path, "rev-parse", "HEAD")
    second = upstream.commit("second")
    repo.update_ref("refs/heads/gate-approved", first, None)
    with pytest.raises(proc.CommandError):
        repo.update_ref("refs/heads/gate-approved", second, None)
    with pytest.raises(proc.CommandError):
        repo.update_ref("refs/heads/gate-approved", second, second)
    assert repo.rev("refs/heads/gate-approved") == first
    repo.update_ref("refs/heads/gate-approved", second, first)
    assert repo.rev("refs/heads/gate-approved") == second


def test_advance_main_does_not_run_hooks(upstream: Upstream, tmp_path: Path) -> None:
    clone = tmp_path / "gate"
    git(tmp_path, "clone", "-q", str(upstream.path), str(clone))
    ran = tmp_path / "hook-ran"
    hook = clone / ".git" / "hooks" / "post-merge"
    hook.write_text(f"#!/bin/sh\ntouch '{ran}'\n")
    hook.chmod(0o755)
    upstream.write("Widget.qml", "import QtQuick\nItem { width: 2 }\n")
    new = upstream.commit()
    git(clone, "fetch", "-q")

    advance_main(Repo(clone), new)
    assert git(clone, "rev-parse", "HEAD") == new
    assert not ran.exists()
    # The hook itself works: a plain merge runs it.
    git(clone, "reset", "-q", "--hard", "HEAD~1")
    git(clone, "merge", "-q", "--ff-only", new)
    assert ran.exists()


def test_rev_does_not_take_options(upstream: Upstream) -> None:
    assert upstream.repo.rev("--output=/tmp/x") is None
    assert upstream.repo.commit("HEAD") == git(upstream.path, "rev-parse", "HEAD")


def test_hook_environment_does_not_redirect_git(
    upstream: Upstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = Upstream(tmp_path / "other")
    other.write("x", "y")
    other.commit()
    monkeypatch.setenv("GIT_DIR", str(other.path / ".git"))
    assert upstream.repo.head() == git(upstream.path, "--git-dir", ".git", "rev-parse", "HEAD")


def test_default_branch_falls_back_to_main(upstream: Upstream, tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(upstream.path), str(clone))
    assert Repo(clone).default_branch() == "main"
    git(clone, "remote", "set-head", "origin", "-d")
    assert Repo(clone).default_branch() == "main"
