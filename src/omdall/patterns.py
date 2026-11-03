"""Pattern matches for the structural checks. Findings, never verdicts."""

import posixpath
import re

# Paths no plugin has a legitimate use for: git internals, ssh keys and
# authorisations, sudo rules. Adding or changing one is a hard failure.
HARD_PATH = re.compile(r"(^|/)\.git/|(^|/)\.ssh/|(^|/)authorized_keys$|(^|/)sudoers$")

# Paths a plugin rarely has business touching, though some do (a systemd/
# directory of QML, a CA bundle). A finding for the reviewer, and a hard failure
# for an executable file.
DENY_PATH = re.compile(
    r"\.service$|\.timer$|\.socket$|\.path$|\.desktop$|\.pem$|\.key$|\.p12$"
    r"|(^|/)systemd/|(^|/)omarchy/hooks"
)

# Added lines that look like download-and-execute, encoded payloads piped into a
# shell, reverse shells, or privilege escalation via a pipe.
DANGER_LINE = re.compile(
    r"(curl|wget)[^|]*\|\s*(ba|z|da|k)?sh(\s|$)"
    r"|base64\s+(-d|--decode)[^|]*\|"
    r"|(nc|ncat)\s.*-[a-z]*e\s"
    r"|/dev/tcp/"
    r"|\|\s*(sudo|pkexec)\s",
    re.IGNORECASE,
)

# Exactly what the reviewer is good at; collected as hints, never auto-failed,
# because plenty of legitimate plugin code uses these.
HINT_RE = re.compile(
    r"curl|wget|eval|new Function|Function\(|subprocess|os\.system|os\.popen|child_process"
    r"|XMLHttpRequest|fetch\(|WebSocket|socket|base64|pkexec|sudo|systemctl|chmod|rm -rf"
    r"|/etc/|api[_ -]?key|token|secret|password|\.env\b|ssh|gpg|keyring"
)

# A `filter` attribute being set (`filter`, `filter=lfs`) in a .gitattributes
# line, as git separates states: by blanks, or right after a quoted pattern.
# `-filter` and `!filter` unset it. A pattern that is itself named `filter`
# matches too; that only fails closed.
ATTR_FILTER = re.compile(rb'(^|[\s"])filter(=|\s|$)')

# The first line of a Git LFS pointer file, including the older spec URLs
# git-lfs still accepts.
LFS_POINTER = re.compile(
    rb"version (https://git-lfs\.github\.com/spec/v1|https://hawser\.github\.com/spec/v1"
    rb"|http://git-media\.io/v/2)"
)
LFS_POINTER_MAX = 1024

# What each asset type's contents start with. A file with an asset suffix and
# other contents is not the image or font its name claims.
ASSET_MAGIC: dict[str, re.Pattern[bytes]] = {
    ".png": re.compile(rb"\x89PNG\r\n\x1a\n"),
    ".jpg": re.compile(rb"\xff\xd8\xff"),
    ".jpeg": re.compile(rb"\xff\xd8\xff"),
    ".gif": re.compile(rb"GIF8[79]a"),
    ".webp": re.compile(rb"RIFF.{4}WEBP", re.DOTALL),
    ".ico": re.compile(rb"\x00\x00\x01\x00"),
    ".avif": re.compile(rb".{4}ftypavi[fs]", re.DOTALL),
    ".bmp": re.compile(rb"BM"),
    ".woff": re.compile(rb"wOFF"),
    ".woff2": re.compile(rb"wOF2"),
    ".ttf": re.compile(rb"\x00\x01\x00\x00|true|OTTO"),
}
ASSET_SUFFIXES = tuple(ASSET_MAGIC)

# Files something loads or runs as code or configuration. Binary to git, such a
# file reaches the reviewer as "Binary files differ" and nothing else.
CODE_SUFFIXES = (
    ".qml",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".py",
    ".pl",
    ".rb",
    ".lua",
    ".json",
    ".toml",
    ".ini",
    ".conf",
    ".desktop",
    ".service",
    ".timer",
    ".socket",
    ".path",
)
CODE_NAMES = ("qmldir",)

# Native code Qt or a runtime can load (a qmldir `plugin` line, for one).
NATIVE_SUFFIX = re.compile(r"\.(so(\.[0-9]+)*|node|dll|dylib)$", re.IGNORECASE)

# A plugin id as `omarchy plugin validate` accepts it. The id names the
# installed copy's directory, so it must never be able to name another path.
VALID_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def valid_plugin_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and VALID_ID.fullmatch(value) is not None
        and ".." not in value
        and not value.startswith("omarchy.")
    )


def is_hard_path(path: str) -> bool:
    return HARD_PATH.search(path) is not None


def is_denied(path: str) -> bool:
    """Any protected path, hard or not."""
    return is_hard_path(path) or DENY_PATH.search(path) is not None


def is_known_asset(path: str) -> bool:
    return path.lower().endswith(ASSET_SUFFIXES)


def asset_matches(path: str, head: bytes) -> bool:
    """Whether the start of an asset file is what its suffix says it is."""
    magic = ASSET_MAGIC.get(posixpath.splitext(path.lower())[1])
    return magic is not None and magic.match(head) is not None


def is_code_path(path: str) -> bool:
    lower = path.lower()
    return lower.endswith(CODE_SUFFIXES) or posixpath.basename(lower) in CODE_NAMES


def is_native_path(path: str) -> bool:
    return NATIVE_SUFFIX.search(path) is not None


def escapes_plugin(entry_point: str) -> bool:
    return entry_point.startswith("/") or re.search(r"(^|/)\.\.(/|$)", entry_point) is not None
