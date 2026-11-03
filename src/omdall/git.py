"""git, through plumbing where it exists and NUL-separated output where it does not."""

import os
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from . import proc

# Options for every diff the gate reads. The user's config must not change what
# the reviewer sees: no colour, no external diff or textconv, fixed prefixes,
# deterministic rename detection.
_DIFF_OPTS = (
    "--no-color",
    "--no-ext-diff",
    "--no-textconv",
    "--src-prefix=a/",
    "--dst-prefix=b/",
    "-M",
)

DOC_EXCLUDES = (".", ":(exclude)*.md", ":(exclude)*.txt", ":(exclude)LICENSE")


@dataclass(frozen=True, slots=True)
class Change:
    """One file in a diff. `path` is the destination for renames and copies."""

    status: str
    path: str
    old_path: str | None
    old_mode: str
    new_mode: str
    new_blob: str
    binary: bool

    @property
    def became_executable(self) -> bool:
        return self.new_mode == "100755" and self.old_mode != "100755"


@dataclass(frozen=True, slots=True)
class CommitInfo:
    sha: str
    author: str
    date: str
    subject: str


def parse_raw_z(data: bytes) -> list[tuple[str, str, str, str, str, str | None]]:
    """`git diff --raw -z --no-abbrev` → (status, path, old_mode, new_mode, new_blob, old_path)."""
    out: list[tuple[str, str, str, str, str, str | None]] = []
    tokens = data.split(b"\0")
    i = 0
    while i < len(tokens):
        meta = tokens[i]
        i += 1
        if not meta:
            continue
        if not meta.startswith(b":"):
            raise ValueError(f"unexpected raw diff record: {meta[:80]!r}")
        old_mode, new_mode, _old_blob, new_blob, status = meta[1:].decode("ascii").split(" ")
        if status[:1] in ("R", "C"):
            old_path, path = os.fsdecode(tokens[i]), os.fsdecode(tokens[i + 1])
            i += 2
        else:
            old_path, path = None, os.fsdecode(tokens[i])
            i += 1
        out.append((status[:1], path, old_mode, new_mode, new_blob, old_path))
    return out


def parse_numstat_z(data: bytes) -> dict[str, bool]:
    """`git diff --numstat -z` → {destination path: is binary}."""
    out: dict[str, bool] = {}
    tokens = data.split(b"\0")
    i = 0
    while i < len(tokens):
        record = tokens[i]
        i += 1
        if not record:
            continue
        added, _deleted, path = record.split(b"\t", 2)
        if not path:
            path = tokens[i + 1]
            i += 2
        out[os.fsdecode(path)] = added == b"-"
    return out


def parse_status_z(data: bytes) -> list[tuple[str, str]]:
    """`git status --porcelain=v1 -z` → (two-letter status, path). A rename or
    copy is reported once, under its new path."""
    out: list[tuple[str, str]] = []
    tokens = data.split(b"\0")
    i = 0
    while i < len(tokens):
        record = tokens[i]
        i += 1
        if not record:
            continue
        if len(record) < 4 or record[2:3] != b" ":
            raise ValueError(f"unexpected status record: {record[:80]!r}")
        code = record[:2].decode("ascii")
        if "R" in code or "C" in code:
            i += 1
        out.append((code, os.fsdecode(record[3:])))
    return out


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path

    def git(
        self,
        *args: str,
        check: bool = True,
        input: bytes | None = None,
        no_attributes: bool = False,
        no_hooks: bool = False,
    ) -> proc.Result:
        # Attributes would let the plugin's own .gitattributes mark code as
        # binary (hiding it from the patch) or rewrite archive contents.
        env = {"GIT_ATTR_SOURCE": self.empty_tree} if no_attributes else None
        # The gate's own merges are of approved commits; the tripwire they would
        # start would also wait for the lock this run holds.
        hooks = ["-c", "core.hooksPath=/dev/null"] if no_hooks else []
        return proc.run(
            ["git", "-C", str(self.path), *hooks, *args], check=check, input=input, env=env
        )

    def ok(self, *args: str, no_attributes: bool = False, no_hooks: bool = False) -> bool:
        return self.git(*args, check=False, no_attributes=no_attributes, no_hooks=no_hooks).ok

    def rev(self, ref: str) -> str | None:
        r = self.git("rev-parse", "--verify", "--quiet", "--end-of-options", ref, check=False)
        return r.text if r.ok and r.text else None

    def commit(self, ref: str) -> str | None:
        return self.rev(f"{ref}^{{commit}}")

    def head(self) -> str | None:
        return self.rev("HEAD")

    def is_repo(self) -> bool:
        return self.path.is_dir() and self.ok("rev-parse", "--git-dir")

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return self.ok("merge-base", "--is-ancestor", ancestor, descendant)

    @cached_property
    def empty_tree(self) -> str:
        return proc.run(
            ["git", "-C", str(self.path), "hash-object", "-t", "tree", "--stdin"], input=b""
        ).text

    def current_branch(self) -> str | None:
        r = self.git("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        return r.text if r.ok and r.text else None

    def default_branch(self) -> str | None:
        r = self.git("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False)
        if r.ok and r.text:
            return r.text.removeprefix("origin/")
        r = self.git("ls-remote", "--symref", "origin", "HEAD", check=False)
        if r.ok:
            for line in r.text.splitlines():
                if line.startswith("ref:"):
                    ref = line.split()[1]
                    return ref.removeprefix("refs/heads/")
        for name in ("main", "master"):
            if self.rev(f"refs/remotes/origin/{name}"):
                return name
        return None

    def upstream(self, branch: str) -> str | None:
        return self.rev(f"refs/remotes/origin/{branch}")

    def is_clean(self) -> bool:
        return self.ok("diff-index", "--quiet", "HEAD", "--")

    def _status(self, *extra: str) -> list[tuple[str, str]]:
        out = self.git(
            "--no-optional-locks",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            *extra,
            no_attributes=True,
        ).stdout
        return parse_status_z(out)

    def dirty_paths(self) -> list[str]:
        """Files that differ from HEAD: modified, staged, deleted or untracked,
        but not ignored."""
        return [path for _code, path in self._status()]

    def ignored_paths(self) -> list[str]:
        return [path for code, path in self._status("--ignored") if code == "!!"]

    def update_ref(self, ref: str, sha: str, expected: str | None) -> None:
        """Move `ref` to `sha` only if it still points at `expected`, or, with
        None, only if it does not exist yet. Raises CommandError otherwise."""
        self.git("update-ref", ref, sha, expected or "")

    def remote_url(self, name: str = "origin") -> str:
        r = self.git("remote", "get-url", name, check=False)
        return r.text if r.ok else ""

    def hook_dirs(self) -> tuple[Path, Path] | None:
        """(hooks directory, common git directory), both absolute. The hooks
        directory follows core.hooksPath, wherever that points."""
        r = self.git(
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "hooks",
            "--git-common-dir",
            check=False,
        )
        lines = r.text.splitlines() if r.ok else []
        if len(lines) != 2:
            return None
        return Path(lines[0]), Path(lines[1])

    def diff(self, base: str, new: str, *pathspec: str) -> bytes:
        args = ["diff", *_DIFF_OPTS, base, new]
        if pathspec:
            args += ["--", *pathspec]
        return self.git(*args, no_attributes=True).stdout

    def diff_stat(self, base: str, new: str) -> str:
        return self.git("diff", *_DIFF_OPTS, "--stat", base, new, no_attributes=True).text

    def changes(self, base: str, new: str) -> list[Change]:
        raw = self.git(
            "diff", *_DIFF_OPTS, "--raw", "-z", "--no-abbrev", base, new, no_attributes=True
        ).stdout
        numstat = self.git(
            "diff", *_DIFF_OPTS, "--numstat", "-z", base, new, no_attributes=True
        ).stdout
        binary = parse_numstat_z(numstat)
        return [
            Change(status, path, old_path, old_mode, new_mode, new_blob, binary.get(path, False))
            for status, path, old_mode, new_mode, new_blob, old_path in parse_raw_z(raw)
        ]

    def blob(self, spec: str) -> bytes | None:
        """Contents of `<sha>` or `<rev>:<path>`, or None when it does not exist."""
        r = self.git("cat-file", "blob", spec, check=False)
        return r.stdout if r.ok else None

    def blob_sizes(self, shas: Iterable[str]) -> dict[str, int]:
        """Sizes of the blobs among `shas`; anything missing or not a blob is left out."""
        wanted = list(dict.fromkeys(shas))
        if not wanted:
            return {}
        out = self.git(
            "cat-file",
            "--batch-check=%(objectname) %(objecttype) %(objectsize)",
            input="".join(f"{s}\n" for s in wanted).encode(),
        ).text
        sizes: dict[str, int] = {}
        for line in out.splitlines():
            parts = line.split(" ")
            if len(parts) == 3 and parts[1] == "blob":
                sizes[parts[0]] = int(parts[2])
        return sizes

    def tree_paths(self, rev: str) -> list[str]:
        """Every file in the tree of `rev`, at any depth."""
        out = self.git("ls-tree", "-r", "-z", "--full-tree", "--name-only", rev).stdout
        return [os.fsdecode(p) for p in out.split(b"\0") if p]

    def exists(self, spec: str) -> bool:
        return self.ok("cat-file", "-e", spec)

    def archive(self, rev: str) -> bytes:
        return self.git("archive", "--format=tar", rev, no_attributes=True).stdout

    def subject(self, rev: str) -> str:
        r = self.git("log", "-1", "--format=%s", rev, check=False)
        return r.text if r.ok else ""

    def commit_info(self, rev: str) -> CommitInfo | None:
        r = self.git(
            "log", "-1", "--no-show-signature", "--format=%H%x00%an%x00%aI%x00%s",
            "--end-of-options", rev, check=False,
        )  # fmt: skip
        parts = r.text.split("\0") if r.ok else []
        return CommitInfo(*parts) if len(parts) == 4 else None

    def count(self, old: str, new: str) -> int | None:
        """How many commits are in `old..new`, or None when git cannot tell."""
        r = self.git("rev-list", "--count", f"{old}..{new}", check=False)
        return int(r.text) if r.ok and r.text.isdigit() else None

    def config_get(self, key: str) -> str:
        """One value from this repository's config, or "" when it is unset."""
        r = self.git("config", "--get", key, check=False)
        return r.text if r.ok else ""

    def log_lines(self, old: str, new: str, fmt: str) -> list[str]:
        r = self.git("log", f"--format={fmt}", f"{old}..{new}", check=False)
        return r.text.splitlines() if r.ok and r.text else []

    def hash_object(self, data: bytes) -> str:
        r = self.git("hash-object", "--no-filters", "--stdin", input=data, check=False)
        return r.text if r.ok else ""
