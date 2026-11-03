"""adopt and the unguarded list: which installed plugins the gate offers to take."""

import json
from pathlib import Path

import pytest

from omdall.commands import adopt
from omdall.commands.add import is_local_url
from omdall.context import Context
from omdall.output import AlreadyGuarded, GateError, NotInstalled
from support import Upstream, git


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("/srv/git/x", True),
        ("../x", True),
        ("file:///srv/x", True),
        ("FILE:///srv/x", True),
        ("https://github.com/a/b", False),
        ("git@github.com:a/b", False),
        ("ssh://host/x", False),
        ("ext::sh -c x", False),
        ("-ux", False),
        ("", False),
    ],
)
def test_is_local_url(url: str, local: bool) -> None:
    assert is_local_url(url) is local


@pytest.mark.parametrize(
    ("is_git", "origin", "reason"),
    [
        (False, "https://example.invalid/acme/x", "no_git"),
        (True, "", "no_origin"),
        (True, "/srv/git/x", "local_origin"),
        (True, "http://example.invalid/acme/x", "insecure_url"),
        (True, "git://example.invalid/acme/x", "insecure_url"),
        (True, "ext::sh -c x", "insecure_url"),
        (True, "https://example.invalid/acme/taken", "name_taken"),
        (True, "https://example.invalid/acme/x", None),
    ],
)
def test_adopt_problem(ctx: Context, is_git: bool, origin: str, reason: str | None) -> None:
    (ctx.cfg.root / "taken").mkdir(parents=True)
    assert adopt.adopt_problem(ctx, is_git, origin) == reason


def install(ctx: Context, plugin_id: str, **manifest: object) -> Path:
    directory = ctx.cfg.installed_root / plugin_id
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(json.dumps({"id": plugin_id, **manifest}))
    return directory


def test_unguarded_lists_what_no_clone_maps_to(ctx: Context, upstream: Upstream) -> None:
    git(upstream.path.parent, "clone", "-q", str(upstream.path), str(ctx.clone_dir("demo")))
    install(ctx, "selftest.demo")
    install(ctx, "acme.hand", name="Hand \x1b[1m")
    install(ctx, "omarchy.core")
    renamed = install(ctx, "acme.renamed")
    (renamed / "manifest.json").write_text('{"id": "acme.other"}')
    (ctx.cfg.installed_root / "acme.link").symlink_to(ctx.cfg.installed_root / "acme.hand")
    outside = ctx.cfg.root.parent / "outside"
    outside.mkdir()
    (outside / "manifest.json").write_text('{"id": "acme.sneaky"}')
    sneaky = ctx.cfg.installed_root / "acme.sneaky"
    sneaky.mkdir()
    (sneaky / "manifest.json").symlink_to(outside / "manifest.json")

    [record] = adopt.unguarded(ctx)
    assert record.id == "acme.hand"
    assert record.name == "Hand \\x1b[1m"
    assert (record.git, record.origin, record.head, record.dirty) == (False, None, None, False)
    assert (record.adoptable, record.reason) == (False, "no_git")


def test_unguarded_ignores_a_repository_further_up(ctx: Context) -> None:
    git(ctx.cfg.config_home.parent, "init", "-q", str(ctx.cfg.config_home))
    install(ctx, "acme.hand")
    [record] = adopt.unguarded(ctx)
    assert (record.git, record.reason) == (False, "no_git")


def test_unguarded_reads_origin_without_credentials(ctx: Context, upstream: Upstream) -> None:
    directory = ctx.cfg.installed_root / "selftest.demo"
    git(upstream.path.parent, "clone", "-q", str(upstream.path), str(directory))
    git(directory, "remote", "set-url", "origin", "https://me:token@example.invalid/acme/demo")
    [record] = adopt.unguarded(ctx)
    assert record.origin == "https://example.invalid/acme/demo"
    assert (record.git, record.adoptable, record.reason) == (True, True, None)
    assert record.head == upstream.repo.head()


def test_resolve_refusals(ctx: Context, upstream: Upstream) -> None:
    with pytest.raises(GateError, match="not a plugin id"):
        adopt.resolve(ctx, "omarchy.core")
    with pytest.raises(GateError, match="not a plugin id"):
        adopt.resolve(ctx, "../x")
    with pytest.raises(NotInstalled):
        adopt.resolve(ctx, "acme.missing")
    install(ctx, "selftest.demo")
    git(upstream.path.parent, "clone", "-q", str(upstream.path), str(ctx.clone_dir("demo")))
    with pytest.raises(AlreadyGuarded):
        adopt.resolve(ctx, "selftest.demo")
