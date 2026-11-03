import re
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from omdall import __version__
from omdall.config import DEFAULT_MAX_PATCH, DEFAULT_TIMEOUT, Config, Overrides
from omdall.output import GateError

SELF = Path("/repo/bin/omdall")


def test_defaults_follow_home_and_xdg() -> None:
    cfg = Config.from_env({"HOME": "/h", "USER": "me"}, SELF)
    assert cfg.root == Path("/h/Work/omarchy-plugins")
    assert cfg.state_root == Path("/h/.local/state/omdall")
    assert cfg.installed_root == Path("/h/.config/omarchy/plugins")
    assert cfg.agent_file == Path("/h/.config/opencode/agents/omdall-reviewer.md")
    assert cfg.agent_src == Path("/repo/agents/omdall-reviewer.md.in")
    assert cfg.review_timeout == DEFAULT_TIMEOUT
    assert cfg.max_patch_bytes == DEFAULT_MAX_PATCH
    assert cfg.notify_policy == "all"
    assert cfg.model == ""
    assert cfg.user == "me"


def test_xdg_dirs() -> None:
    cfg = Config.from_env({"HOME": "/h", "XDG_STATE_HOME": "/s", "XDG_CONFIG_HOME": "/c"}, SELF)
    assert cfg.state_root == Path("/s/omdall")
    assert cfg.installed_root == Path("/c/omarchy/plugins")


def test_environment_settings() -> None:
    env = {
        "HOME": "/h",
        "OMDALL_ROOT": "/r",
        "OMDALL_STATE": "/s",
        "OMDALL_AGENT": "other-reviewer",
        "OMDALL_MODEL": "venice/m",
        "OMDALL_NOTIFY": "ready",
        "OMDALL_TIMEOUT": "60",
        "OMDALL_MAX_PATCH": "1000",
    }
    cfg = Config.from_env(env, SELF)
    assert (cfg.root, cfg.state_root) == (Path("/r"), Path("/s"))
    assert cfg.agent_file == Path("/h/.config/opencode/agents/other-reviewer.md")
    assert (cfg.model, cfg.notify_policy) == ("venice/m", "ready")
    assert (cfg.review_timeout, cfg.max_patch_bytes) == (60, 1000)


def test_overrides_beat_the_environment() -> None:
    env = {
        "HOME": "/h",
        "OMDALL_ROOT": "/env-root",
        "OMDALL_STATE": "/env-state",
        "OMDALL_AGENT": "env-agent",
        "OMDALL_MODEL": "env/model",
        "OMDALL_NOTIFY": "all",
        "OMDALL_TIMEOUT": "abc",
        "OMDALL_MAX_PATCH": "abc",
    }
    over = Overrides(
        root="/r",
        state="/s",
        agent="flag-agent",
        model="flag/model",
        notify="none",
        timeout="30",
        max_patch="500",
    )
    cfg = Config.from_env(env, SELF, over)
    assert (cfg.root, cfg.state_root) == (Path("/r"), Path("/s"))
    assert cfg.agent == "flag-agent"
    assert (cfg.model, cfg.notify_policy) == ("flag/model", "none")
    assert (cfg.review_timeout, cfg.max_patch_bytes) == (30, 500)


def test_unset_overrides_fall_back_to_the_environment() -> None:
    env = {"HOME": "/h", "OMDALL_ROOT": "/env-root"}
    cfg = Config.from_env(env, SELF, Overrides(model="flag/model"))
    assert cfg.root == Path("/env-root")
    assert cfg.model == "flag/model"


def test_empty_counts_as_unset() -> None:
    cfg = Config.from_env({"HOME": "/h", "OMDALL_ROOT": "", "OMDALL_TIMEOUT": ""}, SELF)
    assert cfg.root == Path("/h/Work/omarchy-plugins")
    assert cfg.review_timeout == DEFAULT_TIMEOUT


@pytest.mark.parametrize("value", ["abc", "0", "-5", "7m", "1.5"])
def test_bad_numbers_are_rejected(value: str) -> None:
    with pytest.raises(GateError, match="OMDALL_TIMEOUT"):
        Config.from_env({"HOME": "/h", "OMDALL_TIMEOUT": value}, SELF)
    with pytest.raises(GateError, match="OMDALL_MAX_PATCH"):
        Config.from_env({"HOME": "/h", "OMDALL_MAX_PATCH": value}, SELF)


@pytest.mark.parametrize("value", ["abc", "0", "-5", "7m", "1.5"])
def test_bad_number_flags_name_the_flag(value: str) -> None:
    env = {"HOME": "/h", "OMDALL_TIMEOUT": "60"}
    with pytest.raises(GateError, match=r"^--timeout must"):
        Config.from_env(env, SELF, Overrides(timeout=value))
    with pytest.raises(GateError, match=r"^--max-patch must"):
        Config.from_env(env, SELF, Overrides(max_patch=value))


def test_bad_notify_policy_is_rejected() -> None:
    with pytest.raises(GateError, match="all, ready, none"):
        Config.from_env({"HOME": "/h", "OMDALL_NOTIFY": "sometimes"}, SELF)
    with pytest.raises(GateError, match=r"^--notify must be one of all, ready, none"):
        Config.from_env({"HOME": "/h"}, SELF, Overrides(notify="sometimes"))


REPO = Path(__file__).parents[2]


def with_config(tmp_path: Path, text: str | bytes, **env: str) -> dict[str, str]:
    """An environment whose config file holds text."""
    path = tmp_path / "xdg" / "omdall" / "config.toml"
    path.parent.mkdir(parents=True)
    if isinstance(text, str):
        text = text.encode()
    path.write_bytes(text)
    return {"HOME": "/h", "XDG_CONFIG_HOME": str(tmp_path / "xdg"), **env}


def defaults(cfg: Config) -> Config:
    """The built-in defaults, with no config file, in the same config home as cfg."""
    built_in = Config.from_env({"HOME": "/h", "XDG_CONFIG_HOME": "/nonexistent"}, SELF)
    return replace(built_in, config_home=cfg.config_home)


def test_config_file_settings(tmp_path: Path) -> None:
    env = with_config(
        tmp_path,
        'root = "/r"\nstate = "~/st"\nagent = "a"\nmodel = "venice/m"\n'
        'notify = "ready"\ntimeout = 60\nmax-patch = 1000\n',
    )
    cfg = Config.from_env(env, SELF)
    assert cfg.config_file == tmp_path / "xdg" / "omdall" / "config.toml"
    assert (cfg.root, cfg.state_root) == (Path("/r"), Path("/h/st"))
    assert (cfg.agent, cfg.model, cfg.notify_policy) == ("a", "venice/m", "ready")
    assert (cfg.review_timeout, cfg.max_patch_bytes) == (60, 1000)


def test_config_file_has_the_lowest_priority(tmp_path: Path) -> None:
    env = with_config(
        tmp_path,
        'model = "file/model"\ntimeout = 60\nagent = "file-agent"\nnotify = "ready"\n',
        OMDALL_MODEL="env/model",
        OMDALL_TIMEOUT="",
        OMDALL_AGENT="env-agent",
    )
    cfg = Config.from_env(env, SELF, Overrides(agent="flag-agent"))
    assert cfg.model == "env/model"
    assert cfg.review_timeout == 60
    assert cfg.agent == "flag-agent"
    assert cfg.notify_policy == "ready"


def test_missing_config_file_is_fine(tmp_path: Path) -> None:
    cfg = Config.from_env({"HOME": "/h", "XDG_CONFIG_HOME": str(tmp_path)}, SELF)
    assert cfg.model == ""
    assert cfg.config_file == tmp_path / "omdall" / "config.toml"


def test_empty_strings_in_the_config_file_count_as_unset(tmp_path: Path) -> None:
    cfg = Config.from_env(with_config(tmp_path, 'root = ""\nmodel = ""\nnotify = ""\n'), SELF)
    assert (cfg.root, cfg.model, cfg.notify_policy) == (Path("/h/Work/omarchy-plugins"), "", "all")


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("model = ", "is not valid TOML"),
        ("colour = 'red'\n", "unknown setting 'colour'"),
        ("max_patch = 1\n", "unknown setting 'max_patch'"),
        ("[gate]\nmodel = 'm'\n", "unknown setting 'gate'"),
        ("timeout = '60'\n", "timeout in .* must be a whole number"),
        ("timeout = true\n", "timeout in .* must be a whole number"),
        ("timeout = 1.5\n", "timeout in .* must be a whole number"),
        ("timeout = 0\n", "timeout in .* must be a positive whole number of seconds, not '0'"),
        ("max-patch = -5\n", "max-patch in .* must be a positive whole number of bytes"),
        ("model = 7\n", "model in .* must be a string"),
        ("notify = 'sometimes'\n", "notify in .* must be one of all, ready, none"),
        ("root = 'relative/dir'\n", "root in .* must be an absolute path or start with ~/"),
        ("state = '~other/dir'\n", "state in .* must be an absolute path or start with ~/"),
    ],
)
def test_bad_config_files_are_rejected(tmp_path: Path, text: str, error: str) -> None:
    with pytest.raises(GateError, match=error):
        Config.from_env(with_config(tmp_path, text), SELF)


def test_bad_config_file_value_is_ignored_when_overridden(tmp_path: Path) -> None:
    env = with_config(tmp_path, "timeout = 0\n", OMDALL_TIMEOUT="5")
    assert Config.from_env(env, SELF).review_timeout == 5


def test_config_file_that_is_not_utf8(tmp_path: Path) -> None:
    with pytest.raises(GateError, match="not valid UTF-8"):
        Config.from_env(with_config(tmp_path, b"model = 'caf\xe9'\n"), SELF)


def test_unreadable_config_file(tmp_path: Path) -> None:
    (tmp_path / "omdall" / "config.toml").mkdir(parents=True)
    with pytest.raises(GateError, match="cannot read"):
        Config.from_env({"HOME": "/h", "XDG_CONFIG_HOME": str(tmp_path)}, SELF)


def test_relative_xdg_dirs_are_ignored(tmp_path: Path) -> None:
    env = {"HOME": "/h", "XDG_CONFIG_HOME": "cfg", "XDG_STATE_HOME": "state"}
    cfg = Config.from_env(env, SELF)
    assert cfg.config_file == Path("/h/.config/omdall/config.toml")
    assert cfg.state_root == Path("/h/.local/state/omdall")


def test_example_config_is_all_commented_out(tmp_path: Path) -> None:
    text = (REPO / "config.example.toml").read_text()
    assert tomllib.loads(text) == {}
    cfg = Config.from_env(with_config(tmp_path, text), SELF)
    assert cfg == defaults(cfg)


def test_example_config_values_are_the_defaults(tmp_path: Path) -> None:
    """Uncommenting every setting in the example changes nothing."""
    text = (REPO / "config.example.toml").read_text()
    settings = [line[2:] for line in text.splitlines() if re.match(r"# [a-z-]+ = ", line)]
    keys = {line.split(" = ")[0] for line in settings}
    assert keys == {"root", "state", "agent", "model", "notify", "timeout", "max-patch"}
    cfg = Config.from_env(with_config(tmp_path, "\n".join(settings) + "\n"), SELF)
    assert cfg == defaults(cfg)
    assert (cfg.review_timeout, cfg.max_patch_bytes) == (DEFAULT_TIMEOUT, DEFAULT_MAX_PATCH)


def test_version_matches_pyproject() -> None:
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    assert tomllib.loads(pyproject.read_text())["project"]["version"] == __version__
