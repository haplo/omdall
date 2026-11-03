"""Scratch git repositories for the tests."""

import json
import os
import subprocess
from pathlib import Path

from omdall.git import Repo

MANIFEST = {
    "schemaVersion": 1,
    "id": "selftest.demo",
    "name": "Selftest Demo",
    "kinds": ["bar-widget"],
    "entryPoints": {"barWidget": "Widget.qml"},
    "barWidget": {"defaultSection": "right"},
}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


class Upstream:
    """A scratch repository to build candidate commits in."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True, exist_ok=True)
        git(path, "init", "-q")

    def write(self, rel: str | bytes, content: str | bytes, mode: int | None = None) -> None:
        p = Path(os.fsdecode(self.path)) / os.fsdecode(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            content = content.encode()
        p.write_bytes(content)
        if mode is not None:
            p.chmod(mode)

    def manifest(self, **changes: object) -> None:
        self.write("manifest.json", json.dumps({**MANIFEST, **changes}, indent=2))

    def commit(self, message: str = "change") -> str:
        git(self.path, "add", "-A")
        git(self.path, "commit", "-q", "--allow-empty", "-m", message)
        return git(self.path, "rev-parse", "HEAD")

    @property
    def repo(self) -> Repo:
        return Repo(self.path)
