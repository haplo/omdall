"""Settings, read once from the command line, the environment and the config file."""

import getpass
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path

from .output import ConfigError

APPROVED_REF = "refs/heads/gate-approved"

# More findings than this in one candidate is a hard fail: the reviewer cannot
# give each one real attention, and a human should look instead.
MAX_FINDINGS = 40

NOTIFY_POLICIES = ("all", "ready", "none")

DEFAULT_TIMEOUT = 420
# 2 MiB of diff is roughly 600k-840k tokens, which leaves a 1M-token reviewer
# room for its prompt, findings and answer. Lower it for smaller models.
DEFAULT_MAX_PATCH = 2 * 1024 * 1024

CONFIG_NAME = Path("omdall") / "config.toml"


@dataclass(frozen=True, slots=True)
class Overrides:
    """Settings given on the command line; None means the flag was not given.

    Each field is the flag `--<name>` (underscores become dashes), the variable
    `OMDALL_<NAME>` and the config file key `<name>`.
    """

    root: str | None = None
    state: str | None = None
    agent: str | None = None
    model: str | None = None
    notify: str | None = None
    timeout: str | None = None
    max_patch: str | None = None


def option_flag(field: str) -> str:
    return "--" + config_key(field)


def env_var(field: str) -> str:
    return "OMDALL_" + field.upper()


def config_key(field: str) -> str:
    return field.replace("_", "-")


SETTING_FIELDS = tuple(f.name for f in fields(Overrides))
_INT_FIELDS = frozenset({"timeout", "max_patch"})
_PATH_FIELDS = frozenset({"root", "state"})


@dataclass(frozen=True, slots=True)
class ConfigFile:
    """Settings from the config file, as strings keyed by field name."""

    path: Path
    values: Mapping[str, str]

    def source(self, field: str) -> str:
        return f"{config_key(field)} in {self.path}"


def _file_value(key: str, value: object, home: Path, path: Path) -> str:
    field = key.replace("-", "_")
    if field in _INT_FIELDS:
        # bool is an int to Python, but `timeout = true` is not a number.
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(f"{key} in {path} must be a whole number")
        return str(value)
    if not isinstance(value, str):
        raise ConfigError(f"{key} in {path} must be a string")
    if field in _PATH_FIELDS and value:
        if value == "~" or value.startswith("~/"):
            value = str(home / value[2:])
        if not Path(value).is_absolute():
            raise ConfigError(f"{key} in {path} must be an absolute path or start with ~/")
    return value


def parse_config(text: str, path: Path, home: Path) -> ConfigFile:
    """Parse config file text. Unknown keys and wrong types are errors; an empty
    string counts as unset, like an empty variable."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} is not valid TOML: {e}") from None
    known = {config_key(f) for f in SETTING_FIELDS}
    values: dict[str, str] = {}
    for key, value in data.items():
        if key not in known:
            raise ConfigError(f"unknown setting '{key}' in {path}")
        if text_value := _file_value(key, value, home, path):
            values[key.replace("-", "_")] = text_value
    return ConfigFile(path, values)


def load_config(path: Path, home: Path) -> ConfigFile:
    """The config file at path; a missing file is an empty one."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ConfigFile(path, {})
    except UnicodeDecodeError:
        raise ConfigError(f"{path} is not valid UTF-8") from None
    except OSError as e:
        raise ConfigError(f"cannot read {path}: {e.strerror or e}") from None
    return parse_config(text, path, home)


def _xdg_dir(env: Mapping[str, str], var: str, default: Path) -> Path:
    """An XDG base directory. The spec says relative values are invalid and
    should be ignored, so they fall back to the default like an unset one."""
    value = env.get(var, "")
    return Path(value) if value.startswith("/") else default


def _setting(
    overrides: Overrides, env: Mapping[str, str], file: ConfigFile, field: str
) -> tuple[str, str]:
    """The value of one setting and where it came from: the flag beats the
    environment, which beats the config file. Empty counts as unset."""
    value = getattr(overrides, field)
    if value is not None:
        return value, option_flag(field)
    if value := env.get(env_var(field), ""):
        return value, env_var(field)
    if value := file.values.get(field, ""):
        return value, file.source(field)
    return "", env_var(field)


def _positive_int(raw: str, source: str, default: int, what: str) -> int:
    if not raw:
        return default
    try:
        value = int(raw, 10)
    except ValueError:
        value = 0
    if value <= 0:
        raise ConfigError(f"{source} must be a positive whole number of {what}, not '{raw}'")
    return value


def _current_user(env: Mapping[str, str]) -> str:
    if env.get("USER"):
        return env["USER"]
    try:
        return getpass.getuser()
    except OSError:
        return "unknown"


@dataclass(frozen=True, slots=True)
class Config:
    root: Path
    state_root: Path
    config_home: Path
    agent: str
    model: str
    notify_policy: str
    review_timeout: int
    max_patch_bytes: int
    self_path: Path
    user: str

    @property
    def config_file(self) -> Path:
        return self.config_home / CONFIG_NAME

    @property
    def installed_root(self) -> Path:
        return self.config_home / "omarchy" / "plugins"

    @property
    def agent_file(self) -> Path:
        return self.config_home / "opencode" / "agents" / f"{self.agent}.md"

    @property
    def agent_src(self) -> Path:
        return self.self_path.parent.parent / "agents" / "omdall-reviewer.md.in"

    @classmethod
    def from_env(
        cls, env: Mapping[str, str], self_path: Path, overrides: Overrides | None = None
    ) -> Config:
        over = overrides or Overrides()
        home = Path(env.get("HOME") or Path.home())
        state_home = _xdg_dir(env, "XDG_STATE_HOME", home / ".local" / "state")
        config_home = _xdg_dir(env, "XDG_CONFIG_HOME", home / ".config")
        file = load_config(config_home / CONFIG_NAME, home)
        root, _ = _setting(over, env, file, "root")
        state, _ = _setting(over, env, file, "state")
        agent, _ = _setting(over, env, file, "agent")
        model, _ = _setting(over, env, file, "model")
        notify, notify_source = _setting(over, env, file, "notify")
        notify = notify or "all"
        if notify not in NOTIFY_POLICIES:
            raise ConfigError(
                f"{notify_source} must be one of {', '.join(NOTIFY_POLICIES)}, not '{notify}'"
            )
        timeout, timeout_source = _setting(over, env, file, "timeout")
        max_patch, max_patch_source = _setting(over, env, file, "max_patch")
        return cls(
            root=Path(root) if root else home / "Work" / "omarchy-plugins",
            state_root=Path(state) if state else state_home / "omdall",
            config_home=config_home,
            agent=agent or "omdall-reviewer",
            model=model,
            notify_policy=notify,
            review_timeout=_positive_int(timeout, timeout_source, DEFAULT_TIMEOUT, "seconds"),
            max_patch_bytes=_positive_int(max_patch, max_patch_source, DEFAULT_MAX_PATCH, "bytes"),
            self_path=self_path,
            user=_current_user(env),
        )
