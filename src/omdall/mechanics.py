"""Structural checks, in two tiers.

Hard failures are things the model cannot judge (a patch too large or not text,
code git shows only as binary), that break the gate's own bookkeeping
(manifest identity, loadability), or that no plugin has a legitimate use for
(ssh keys, sudo rules, git internals); they are a REVIEW FAIL with no model call.
Findings are pattern matches that are usually, but not always, a problem; they
go to the reviewer numbered F1..Fn and each must be explicitly cleared. Keyword
hits go to the reviewer as plain hints.
"""

import io
import json
import posixpath
import tarfile
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from . import patterns, proc
from .config import MAX_FINDINGS
from .git import DOC_EXCLUDES, Change, Repo
from .output import printable
from .plugins import parse_manifest

PASS_LINE = "PASS structural pre-checks"  # noqa: S105 - not a password


@dataclass(slots=True)
class MechResult:
    hard: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.hard

    def mech_text(self) -> str:
        return "".join(f"{line}\n" for line in [*self.hard, *([] if self.hard else [PASS_LINE])])

    def findings_text(self) -> str:
        return "".join(f"F{i} {text}\n" for i, text in enumerate(self.findings, 1))


# ------------------------------------------------------------------ pure checks


def size_problem(size: int, limit: int) -> str | None:
    if size > limit:
        return f"patch is {size} bytes, over the {limit} byte review limit — needs a human"
    return None


def _header_path(line: bytes) -> str:
    rest = line.removeprefix(b"diff --git ").decode("utf-8", "replace")
    for a, b in (("a/", " b/"), ('"a/', ' "b/')):
        if rest.startswith(a):
            return rest[len(a) :].split(b, 1)[0]
    return rest


def non_utf8_files(patch: bytes) -> list[str] | None:
    """Files whose part of the patch is not valid UTF-8, or None if all of it is.

    OpenCode only hands a text attachment to the model when it is valid UTF-8;
    anything else is dropped and the reviewer sees no code at all.
    """
    try:
        patch.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        return None
    files: list[str] = []
    current = ""
    for line in patch.split(b"\n"):
        if line.startswith(b"diff --git "):
            current = _header_path(line)
        try:
            line.decode("utf-8")
        except UnicodeDecodeError:
            name = printable(current) if current else "unknown file"
            if name not in files:
                files.append(name)
    return files


def utf8_problem(patch: bytes) -> str | None:
    files = non_utf8_files(patch)
    if files is None:
        return None
    shown = " ".join(files[:10]) or "unknown file"
    return f"patch is not valid UTF-8, so the reviewer cannot read it: {shown} — needs a human"


def _protected_problem(c: Change) -> str | None:
    if c.status == "D":
        return None
    shown = printable(c.path)
    if patterns.is_hard_path(c.path):
        return f"plugin adds or changes a protected path: {shown} — needs a human"
    if c.new_mode == "100755" and patterns.is_denied(c.path):
        return f"executable in a protected location: {shown} — needs a human"
    return None


def protected_path_problems(changes: Iterable[Change]) -> list[str]:
    """Hard failures for files no plugin has a use for (.git/, .ssh/,
    authorized_keys, sudoers) and for executables anywhere protected."""
    return [p for c in changes if (p := _protected_problem(c))]


def path_findings(changes: Iterable[Change]) -> list[str]:
    """Findings for the other protected paths, and for deleting a protected file.
    A file protected_path_problems reports is not reported again."""
    return [
        f"plugin touches a path it has no business touching: {printable(c.path)}"
        for c in changes
        if patterns.is_denied(c.path) and _protected_problem(c) is None
    ]


def binary_problems(
    changes: Iterable[Change], entry_points: set[str], blob: Callable[[str], bytes | None]
) -> tuple[list[str], list[str]]:
    """(hard failures, findings) for files git treats as binary.

    The patch shows such a file as "Binary files differ", so the reviewer never
    sees its contents. Code, native libraries, entry points and executables are
    hard failures; an asset whose contents do not match its type, and any other
    binary, are findings.
    """
    hard: list[str] = []
    found: list[str] = []
    for c in changes:
        if c.status == "D" or not c.binary:
            continue
        shown = printable(c.path)
        head = (blob(c.new_blob) or b"")[:16]
        if head.startswith(b"\x7fELF") or patterns.is_native_path(c.path):
            hard.append(f"{shown} is a native executable or library — needs a human")
        elif patterns.is_code_path(c.path) or c.path in entry_points or c.new_mode == "100755":
            hard.append(f"{shown} is binary to git, so the reviewer cannot read it — needs a human")
        elif not patterns.is_known_asset(c.path):
            found.append(f"binary file added or changed outside a known asset type: {shown}")
        elif not patterns.asset_matches(c.path, head):
            found.append(f"asset file does not look like its type: {shown}")
    return hard, found


def mode_problems(changes: Iterable[Change]) -> list[str]:
    """Hard failures for symlinks and submodules, which the patch shows only as
    a target path or a `Subproject commit` line."""
    problems: list[str] = []
    for c in changes:
        if c.status == "D":
            continue
        shown = printable(c.path)
        if c.new_mode == "120000":
            problems.append(f"symlink {shown}: plugins may not contain symlinks — needs a human")
        elif c.new_mode == "160000":
            problems.append(f"submodule {shown}: the reviewer cannot see its code — needs a human")
        if posixpath.basename(c.path) == ".gitmodules":
            problems.append(
                f"{shown}: submodule configuration in the plugin (.gitmodules) — needs a human"
            )
    return problems


def exec_findings(changes: Iterable[Change], blob: Callable[[str], bytes | None]) -> list[str]:
    found: list[str] = []
    for c in changes:
        if not c.became_executable:
            continue
        content = blob(c.new_blob) or b""
        if not content.startswith(b"#!"):
            found.append(f"file made executable without a shebang: {printable(c.path)}")
    return found


def attribute_problems(files: dict[str, bytes | None]) -> list[str]:
    """Hard failures for .gitattributes files (path -> contents) that set a filter.

    The patch shows the committed blob, but every checkout runs the filter
    configured on the machine (`git lfs install` sets one up globally), so the
    files on disk would not be the files that were reviewed.
    """
    problems: list[str] = []
    for path, content in files.items():
        shown = printable(path)
        if content is None:
            problems.append(f"{shown} could not be read — needs a human")
            continue
        for raw in content.split(b"\n"):
            line = raw.strip(b" \t\r")
            if line and not line.startswith(b"#") and patterns.ATTR_FILTER.search(line):
                text = printable(line.decode("utf-8", "replace"))[:200]
                problems.append(
                    f".gitattributes sets a filter ({shown}: {text}) — checked-out content "
                    "would differ from the reviewed patch; needs a human"
                )
                break
    return problems


def lfsconfig_problems(paths: Iterable[str]) -> list[str]:
    return [
        f"{printable(p)}: git-lfs configuration in the plugin (.lfsconfig) — needs a human"
        for p in paths
        if posixpath.basename(p) == ".lfsconfig"
    ]


def lfs_pointer_problems(
    changes: Iterable[Change], small_blob: Callable[[str], bytes | None]
) -> list[str]:
    """Changed files that are Git LFS pointers. `small_blob` returns the contents
    of a blob of at most LFS_POINTER_MAX bytes, None for anything larger."""
    return [
        f"{printable(c.path)} is an LFS pointer; the reviewer would see the pointer, "
        "not the file — needs a human"
        for c in changes
        if c.status != "D" and patterns.LFS_POINTER.match(small_blob(c.new_blob) or b"")
    ]


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def manifest_change(
    old: dict[str, Any] | None, new: dict[str, Any] | None
) -> tuple[list[str], list[str]]:
    """(hard failures, findings) for a manifest that changed between two commits.

    The manifest id is how the gate finds the installed copy; it may not drift.
    What the shell loads (kinds, entryPoints) is for the reviewer to judge.
    """
    hard: list[str] = []
    found: list[str] = []
    a = _compact(old.get("id")) if old is not None else "none"
    b = _compact(new.get("id")) if new is not None else "none"
    if a != b:
        hard.append(f"manifest id changed or unreadable ({a} -> {b}) — needs a human")

    def loads(m: dict[str, Any] | None) -> str:
        if m is None:
            return "none"
        return _compact({"entryPoints": m.get("entryPoints"), "kinds": m.get("kinds")})

    a, b = loads(old), loads(new)
    if a != b:
        found.append(f"manifest kinds/entryPoints changed: {a} -> {b}")
    return hard, found


def id_problem(manifest: dict[str, Any]) -> str | None:
    """The gate's own id check, so it holds whether or not `omarchy` can run."""
    value = manifest.get("id")
    if patterns.valid_plugin_id(value):
        return None
    shown = printable(_compact(value) if "id" in manifest else "missing")[:200]
    return f"manifest id is not a valid plugin id ({shown}) — needs a human"


def entry_point_paths(manifest: dict[str, Any] | None) -> set[str]:
    """The files the manifest's entry points name, as paths in the tree."""
    eps = manifest.get("entryPoints") if manifest is not None else None
    if not isinstance(eps, dict):
        return set()
    return {posixpath.normpath(v) for v in eps.values() if isinstance(v, str) and v}


def entry_point_problems(manifest: dict[str, Any], exists: Callable[[str], bool]) -> list[str]:
    eps = manifest.get("entryPoints")
    if eps is None:
        return []
    if not isinstance(eps, dict):
        return [f"entryPoints is not an object: {printable(_compact(eps))[:200]}"]
    problems: list[str] = []
    for value in eps.values():
        if not isinstance(value, str):
            problems.append(f"entryPoints value is not a path: {printable(_compact(value))[:200]}")
        elif not value:
            continue
        elif patterns.escapes_plugin(value):
            problems.append(f"entryPoints escape the plugin directory: {printable(value)}")
        elif not exists(value):
            problems.append(f"entryPoints names a missing file: {printable(value)}")
    return problems


def added_lines(diff: bytes) -> list[str]:
    return [
        line[1:].decode("utf-8", "replace") for line in diff.split(b"\n") if line.startswith(b"+")
    ]


def danger_findings(lines: Iterable[str]) -> list[str]:
    """Download-and-execute in an added line. Callers exclude documentation, so
    a README quoting an install curl cannot raise a finding."""
    return [
        f"added line pipes a download or decoder into a shell: {printable(line[:200])}"
        for line in lines
        if patterns.DANGER_LINE.search(line)
    ]


def hints(lines: Iterable[str]) -> list[str]:
    """`<count> <keyword>` for the 20 most frequent keywords, most frequent first."""
    counts = Counter(m.lower() for line in lines for m in patterns.HINT_RE.findall(line))
    ranked = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    return [f"{n} {word}" for word, n in ranked[:20]]


# ------------------------------------------------------------- against git


def validate_tree(repo: Repo, rev: str) -> str | None:
    """Validate the candidate tree itself, not whatever the clone has checked out."""
    if proc.which("omarchy") is None:
        return "omarchy is not on PATH, so the candidate could not be validated — needs a human"
    with tempfile.TemporaryDirectory(prefix="omdall.") as tmp:
        try:
            with tarfile.open(fileobj=io.BytesIO(repo.archive(rev)), mode="r:") as tar:
                tar.extractall(tmp, filter="data")
        except (proc.CommandError, tarfile.TarError, OSError) as e:
            return f"candidate tree could not be extracted safely: {printable(str(e))[:200]}"
        if not proc.run_quiet(["omarchy", "plugin", "validate", tmp]):
            return "manifest does not validate at this revision"
    return None


def check(
    repo: Repo, old: str | None, new: str, patch: bytes, max_patch_bytes: int
) -> tuple[MechResult, list[str]]:
    """Run every structural check. Returns the result and the added code lines
    (documentation excluded), which also feed the keyword hints."""
    result = MechResult()
    base = old or repo.empty_tree

    if problem := size_problem(len(patch), max_patch_bytes):
        result.hard.append(problem)
    if problem := utf8_problem(patch):
        result.hard.append(problem)

    new_raw = repo.blob(f"{new}:manifest.json")
    new_manifest = parse_manifest(new_raw)

    changes = repo.changes(base, new)
    hard, found = binary_problems(changes, entry_point_paths(new_manifest), repo.blob)
    result.hard += hard
    result.findings += found
    result.hard += mode_problems(changes)
    result.hard += protected_path_problems(changes)
    result.findings += path_findings(changes)
    result.findings += exec_findings(changes, repo.blob)

    # Attributes apply across the whole tree: one added earlier can match a
    # file added now.
    paths = repo.tree_paths(new)
    attributes = {
        p: repo.blob(f"{new}:{p}") for p in paths if posixpath.basename(p) == ".gitattributes"
    }
    result.hard += attribute_problems(attributes)
    result.hard += lfsconfig_problems(paths)
    sizes = repo.blob_sizes(c.new_blob for c in changes if c.status != "D")

    def small_blob(sha: str) -> bytes | None:
        size = sizes.get(sha)
        return repo.blob(sha) if size is not None and size <= patterns.LFS_POINTER_MAX else None

    result.hard += lfs_pointer_problems(changes, small_blob)

    if old:
        old_raw = repo.blob(f"{old}:manifest.json")
        if old_raw != new_raw:
            hard, found = manifest_change(parse_manifest(old_raw), new_manifest)
            result.hard += hard
            result.findings += found

    if new_manifest is None:
        result.hard.append(
            "manifest.json is missing or not a JSON object at this revision — needs a human"
        )
    else:
        if problem := id_problem(new_manifest):
            result.hard.append(problem)
        result.hard += entry_point_problems(new_manifest, lambda p: repo.exists(f"{new}:{p}"))

    if problem := validate_tree(repo, new):
        result.hard.append(problem)

    code = added_lines(repo.diff(base, new, *DOC_EXCLUDES))
    result.findings += danger_findings(code)

    if len(result.findings) > MAX_FINDINGS:
        result.hard.append(
            f"{len(result.findings)} structural findings, over the {MAX_FINDINGS} "
            "the reviewer is asked to clear — needs a human"
        )
    return result, code
