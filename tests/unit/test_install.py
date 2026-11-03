from pathlib import Path

import pytest

from omdall.context import Context
from omdall.install import install_new
from support import Upstream, git

STUB = """\
#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$STUB_OMARCHY_LOG"
if [[ "$1 $2" == "plugin add" ]]; then
  git clone -q "$3" "$STUB_DEST" || exit 1
  if [[ -n ${STUB_WRONG:-} ]]; then
    git -C "$STUB_DEST" commit -q --allow-empty -m 'not approved'
  fi
fi
exit 0
"""


@pytest.fixture
def setup(
    ctx: Context, upstream: Upstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, Path]:
    """A gate clone of `upstream` named demo, and a stub omarchy first on PATH."""
    ctx.cfg.root.mkdir(parents=True)
    git(tmp_path, "clone", "-q", str(upstream.path), str(ctx.clone_dir("demo")))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "omarchy"
    stub.write_text(STUB)
    stub.chmod(0o755)
    log = tmp_path / "omarchy.log"
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("STUB_OMARCHY_LOG", str(log))
    monkeypatch.setenv("STUB_DEST", str(ctx.cfg.installed_root / "selftest.demo"))
    head = ctx.clone("demo").head()
    assert head
    return head, log


def calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.is_file() else []


def test_installs_and_enables(ctx: Context, setup: tuple[str, Path]) -> None:
    head, log = setup
    assert install_new(ctx, "demo", head, enable_after=True)
    idir = ctx.cfg.installed_root / "selftest.demo"
    assert Upstream(idir).repo.head() == head
    assert calls(log) == [
        f"plugin add {ctx.clone_dir('demo')} --yes",
        "plugin enable selftest.demo --section right",
    ]
    assert (idir / ".git" / "hooks" / "post-merge").is_file()
    assert f"demo installed {head}" in (ctx.state.root / "gate.log").read_text()


def test_left_disabled_on_request(ctx: Context, setup: tuple[str, Path]) -> None:
    head, log = setup
    assert install_new(ctx, "demo", head, enable_after=False)
    assert not any(c.startswith("plugin enable") for c in calls(log))


def test_refuses_a_clone_off_the_approved_commit(ctx: Context, setup: tuple[str, Path]) -> None:
    head, log = setup
    git(ctx.clone_dir("demo"), "commit", "-q", "--allow-empty", "-m", "local work")
    assert not install_new(ctx, "demo", head, enable_after=True)
    assert calls(log) == []


def test_disables_a_copy_at_the_wrong_commit(
    ctx: Context, setup: tuple[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    head, log = setup
    monkeypatch.setenv("STUB_WRONG", "1")
    assert not install_new(ctx, "demo", head, enable_after=True)
    assert calls(log)[-1] == "plugin disable selftest.demo"
    assert not any(c.startswith("plugin enable") for c in calls(log))
