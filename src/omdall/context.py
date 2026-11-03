"""What every command needs: settings and the state directory."""

from dataclasses import dataclass
from pathlib import Path

from . import plugins
from .config import Config
from .git import Repo
from .state import State


@dataclass(frozen=True, slots=True)
class Context:
    cfg: Config
    state: State

    @classmethod
    def create(cls, cfg: Config) -> Context:
        return cls(cfg, State(cfg.state_root))

    def clone_dir(self, name: str) -> Path:
        return plugins.clone_dir(self.cfg, name)

    def clone(self, name: str) -> Repo:
        return Repo(self.clone_dir(name))

    def manifest_id(self, name: str) -> str:
        return plugins.manifest_id(self.cfg, name)

    def installed_dir(self, name: str) -> Path | None:
        return plugins.installed_dir(self.cfg, name)
