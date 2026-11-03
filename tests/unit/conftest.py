from collections.abc import Iterator
from pathlib import Path

import pytest

from omdall.config import Config
from omdall.context import Context
from support import Upstream


@pytest.fixture(autouse=True)
def isolated_git(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never read the developer's git config, and give commits a fixed identity."""
    home = tmp_path_factory.mktemp("home")
    gitconfig = home / "gitconfig"
    gitconfig.write_text(
        "[user]\n\tname = gate test\n\temail = gate@example.invalid\n"
        "[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def isolated_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never read the developer's own config file."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg-config")))


@pytest.fixture
def upstream(tmp_path: Path) -> Upstream:
    u = Upstream(tmp_path / "upstream")
    u.manifest()
    u.write("Widget.qml", "import QtQuick\nItem {}\n")
    u.commit("initial import")
    return u


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    env = {
        "HOME": str(tmp_path / "home"),
        "OMDALL_ROOT": str(tmp_path / "root"),
        "OMDALL_STATE": str(tmp_path / "state"),
        "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
        "USER": "tester",
    }
    return Config.from_env(env, tmp_path / "repo" / "bin" / "omdall")


@pytest.fixture
def ctx(cfg: Config) -> Iterator[Context]:
    yield Context.create(cfg)
