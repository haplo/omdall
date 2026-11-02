import subprocess
from pathlib import Path

import pytest

from omarchy_plugin_gate import __version__, cli, proc
from omarchy_plugin_gate.commands import add, doctor
from omarchy_plugin_gate.commands.add import clone_name, insecure_scheme, url_problem
from omarchy_plugin_gate.commands.status import plugin_state
from omarchy_plugin_gate.config import Config, Overrides
from omarchy_plugin_gate.context import Context
from omarchy_plugin_gate.hooks import hook_ok, hook_target, hook_text, install_hook
from omarchy_plugin_gate.output import GateError, printable
from support import Upstream, git

LAUNCHER = Path(__file__).parents[2] / "bin" / "omarchy-plugin-gate"


def gate(*args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(LAUNCHER), *args],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", **env},
        check=False,
    )


def test_launcher_version() -> None:
    r = gate("--version")
    assert (r.returncode, r.stdout) == (0, f"{__version__}\n")


def test_launcher_ignores_pythonpath(tmp_path: Path) -> None:
    evil = tmp_path / "omarchy_plugin_gate"
    evil.mkdir()
    (evil / "__init__.py").write_text("raise SystemExit('hijacked')\n")
    r = gate("--version", PYTHONPATH=str(tmp_path))
    assert r.returncode == 0, r.stderr


def test_unknown_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(LAUNCHER, ["frob"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("omarchy-plugin-gate: unknown command: frob\n")


@pytest.mark.parametrize(
    "argv",
    [
        ["check", "--bogus"],
        ["approve", "demo", "--reas", "x"],
        ["add", "--dir"],
        ["add", "url", "--dir", ""],
        ["status", "-p", ""],
        ["check", "--fix"],
    ],
)
def test_bad_arguments_exit_1(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(LAUNCHER, argv) == 1
    assert capsys.readouterr().err.startswith("omarchy-plugin-gate: ")


def test_help_needs_no_config(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(LAUNCHER, ["check", "--help"]) == 0
    assert "approve <name>" in capsys.readouterr().out


@pytest.fixture
def seen_config(monkeypatch: pytest.MonkeyPatch) -> list[Config]:
    """Capture the Config a command builds, and stop before it does any work."""
    seen: list[Config] = []

    def create(cfg: Config) -> Context:
        seen.append(cfg)
        raise GateError("stopped by the test")

    monkeypatch.setattr(cli.Context, "create", create)
    for var in ("ROOT", "STATE", "AGENT", "MODEL", "NOTIFY", "TIMEOUT", "MAX_PATCH"):
        monkeypatch.delenv(f"OMARCHY_PLUGIN_GATE_{var}", raising=False)
    return seen


@pytest.mark.parametrize(
    "argv",
    [
        ["--root", "/r", "--model=m", "status", "-p", "demo"],
        ["status", "--root=/r", "-p", "demo", "--model", "m"],
        ["--root", "/r", "status", "--model", "m", "-p", "demo"],
        ["--root", "/r", "--model", "m", "_post-merge", "demo", "/x"],
        ["approve", "demo", "--reason", "--root", "/r", "--model", "m"],
    ],
)
def test_setting_options_before_or_after_the_command(
    argv: list[str], seen_config: list[Config]
) -> None:
    assert cli.main(LAUNCHER, argv) == 1
    [cfg] = seen_config
    assert (cfg.root, cfg.model) == (Path("/r"), "m")


def test_every_setting_has_an_option(seen_config: list[Config]) -> None:
    argv = [
        "check",
        *("--root", "/r", "--state", "/s", "--agent", "a", "--model", "m"),
        *("--notify", "ready", "--timeout", "9", "--max-patch", "99"),
    ]
    assert cli.main(LAUNCHER, argv) == 1
    [cfg] = seen_config
    assert (cfg.root, cfg.state_root, cfg.agent, cfg.model) == (Path("/r"), Path("/s"), "a", "m")
    assert (cfg.notify_policy, cfg.review_timeout, cfg.max_patch_bytes) == ("ready", 9, 99)


def test_options_beat_the_environment(
    seen_config: list[Config], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMARCHY_PLUGIN_GATE_MODEL", "env/model")
    monkeypatch.setenv("OMARCHY_PLUGIN_GATE_TIMEOUT", "soon")
    assert cli.main(LAUNCHER, ["check", "--model", "flag/model", "--timeout", "5"]) == 1
    [cfg] = seen_config
    assert (cfg.model, cfg.review_timeout) == ("flag/model", 5)


def test_config_file_is_read_last(
    seen_config: list[Config], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "omarchy-plugin-gate" / "config.toml"
    config.parent.mkdir()
    config.write_text('model = "file/model"\ntimeout = 9\nnotify = "ready"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("OMARCHY_PLUGIN_GATE_TIMEOUT", "8")
    assert cli.main(LAUNCHER, ["check", "--notify", "none"]) == 1
    [cfg] = seen_config
    assert (cfg.model, cfg.review_timeout, cfg.notify_policy) == ("file/model", 8, "none")


def test_bad_config_file_is_reported(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "omarchy-plugin-gate" / "config.toml"
    config.parent.mkdir()
    config.write_text("modle = 'typo'\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert cli.main(LAUNCHER, ["status"]) == 1
    assert f"unknown setting 'modle' in {config}" in capsys.readouterr().err


def test_option_after_the_command_wins(seen_config: list[Config]) -> None:
    assert cli.main(LAUNCHER, ["--model", "first", "doctor", "--model", "second"]) == 1
    assert seen_config[0].model == "second"


@pytest.mark.parametrize(
    "argv",
    [
        ["--model", "", "check"],
        ["check", "--model="],
        ["check", "--timeout"],
        ["--root"],
        ["--mod", "m", "check"],
        ["check", "--max", "1"],
    ],
)
def test_bad_setting_options_exit_1(
    argv: list[str], seen_config: list[Config], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(LAUNCHER, argv) == 1
    assert seen_config == []
    assert capsys.readouterr().err.startswith("omarchy-plugin-gate: ")


def test_help_and_version_after_setting_options(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(LAUNCHER, ["--model", "m", "--version"]) == 0
    assert capsys.readouterr().out == f"{__version__}\n"
    assert cli.main(LAUNCHER, ["--root", "/r", "--help"]) == 0
    assert "--max-patch BYTES" in capsys.readouterr().out


def test_bad_environment_is_reported(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMARCHY_PLUGIN_GATE_TIMEOUT", "soon")
    assert cli.main(LAUNCHER, ["status"]) == 1
    assert "OMARCHY_PLUGIN_GATE_TIMEOUT" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("url", "override", "name"),
    [
        ("https://github.com/o/omasync.git", "", "omasync"),
        ("https://github.com/o/omasync/", "", "omasync"),
        ("git@github.com:o/my plugin.git", "", "my-plugin"),
        ("host:repo", "", "host-repo"),
        ("https://x/y", "custom", "custom"),
    ],
)
def test_clone_name(url: str, override: str, name: str) -> None:
    assert clone_name(url, override) == name


@pytest.mark.parametrize("url", ["https://x/.hidden", "/"])
def test_clone_name_refuses(url: str) -> None:
    with pytest.raises(GateError):
        clone_name(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/o/omasync",
        "ssh://git@github.com/o/omasync.git",
        "git@github.com:o/omasync.git",
        "host:repo",
        "file:///srv/plugins/omasync",
        "/home/me/my plugins/omasync.git",
    ],
)
def test_url_accepted(url: str) -> None:
    assert url_problem(url) is None


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("", "needs a git URL"),
        ("http://example.com/x", "uses http://, which is not authenticated"),
        ("HTTP://example.com/x", "uses http://, which is not authenticated"),
        ("git://example.com/x", "uses git://, which is not authenticated"),
        ("ext::sh -c touch% /tmp/x", "transport helper"),
        ("https::example.com/x", "transport helper"),
        ("fd::17", "transport helper"),
        ("ftp://example.com/x", "uses the ftp:// transport"),
        ("git+ssh://example.com/x", "uses the git+ssh:// transport"),
        ("HTTPS://example.com/x", "uses the HTTPS:// transport"),
        ("-uhack", "looks like an option"),
        ("--upload-pack=x", "looks like an option"),
        ("relative/path", "neither a URL nor an absolute path"),
        ("./plugin", "neither a URL nor an absolute path"),
        ("-host:repo", "looks like an option"),
        ("user@-host:repo", "neither a URL nor an absolute path"),
        ("https://x/\x1b]52;c;x\x07", "contains control characters"),
    ],
)
def test_url_refused(url: str, reason: str) -> None:
    problem = url_problem(url)
    assert problem is not None
    assert reason in problem
    assert printable(problem) == problem


def test_insecure_scheme() -> None:
    assert insecure_scheme("git://x/y") == "git"
    assert insecure_scheme("Http://x/y") == "http"
    assert insecure_scheme("https://x/y") is None
    assert insecure_scheme("/srv/git://x") is None


def test_add_clones_over_allowed_protocols_only(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], object]] = []

    def run(argv: list[str], **kwargs: object) -> proc.Result:
        calls.append((list(argv), kwargs.get("env")))
        return proc.Result(tuple(argv), 128, b"", b"stopped here")

    monkeypatch.setattr(proc, "which", lambda _name: None)
    monkeypatch.setattr(proc, "run", run)
    with pytest.raises(GateError, match="clone failed"):
        add.run(ctx, add.AddArgs("https://example.invalid/demo"))
    ((argv, env),) = calls
    assert argv[:2] == ["git", "clone"]
    assert env == {"GIT_ALLOW_PROTOCOL": "https:ssh:file"}


def test_add_asks_omarchy_about_the_url(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> proc.Result:
        calls.append(list(argv))
        return proc.Result(tuple(argv), 1, b"", b"no")

    monkeypatch.setattr(proc, "which", lambda name: f"/stub/{name}")
    monkeypatch.setattr(proc, "run", run)
    with pytest.raises(GateError, match="omarchy-git-url-check refused"):
        add.run(ctx, add.AddArgs("https://example.invalid/demo"))
    assert calls == [["omarchy-git-url-check", "https://example.invalid/demo"]]
    assert not ctx.clone_dir("demo").exists()


@pytest.mark.parametrize(
    ("approved", "installed", "exists", "held", "state"),
    [
        (None, None, False, None, "not reviewed yet"),
        ("a", "a", True, None, "installed"),
        ("a", "b", True, None, "ready to install"),
        ("a", None, True, None, "ready to install"),
        ("a", None, False, None, "approved, not installed"),
        ("a", "a", True, "c", "held back"),
        ("a", "a", True, "a", "installed"),
        (None, None, False, "c", "held back"),
    ],
)
def test_plugin_state(
    approved: str | None, installed: str | None, exists: bool, held: str | None, state: str
) -> None:
    assert plugin_state(approved, installed, exists, held) == state


def test_printable() -> None:
    assert printable("a\nb\tc\x1b") == "a\\nb\\tc\\x1b"
    assert printable("caf\u00e9 \u2603") == "caf\u00e9 \u2603"
    assert printable("raw\udcff") == "raw\\udcff"


def test_hook_quotes_paths_and_names(tmp_path: Path) -> None:
    cfg = Config.from_env(
        {"HOME": str(tmp_path), "OMARCHY_PLUGIN_GATE_STATE": str(tmp_path / "st ate")},
        tmp_path / "my repo" / "bin" / "omarchy-plugin-gate",
    )
    text = hook_text(cfg, "it's; rm -rf ~")
    assert (
        f"exec '{cfg.self_path}' --root {cfg.root} --state '{cfg.state_root}' "
        "_post-merge 'it'\"'\"'s; rm -rf ~' \"$top\"" in text
    )
    assert f">>'{tmp_path / 'st ate' / 'hooks.log'}' 2>&1" in text
    r = subprocess.run(["bash", "-n"], input=text, text=True, capture_output=True, check=False)
    assert r.returncode == 0, r.stderr


def test_hook_names_its_plugin(cfg: Config) -> None:
    assert '_post-merge demo "$top" >>' in hook_text(cfg, "demo")


def test_no_hook_for_an_unprintable_name(cfg: Config, upstream: Upstream) -> None:
    problem = install_hook(cfg, upstream.path, "evil\nrm -rf ~")
    assert problem == "the plugin name evil\\nrm -rf ~ cannot go into a hook"
    assert not (upstream.path / ".git" / "hooks" / "post-merge").exists()


def test_hook_install_and_detection(cfg: Config, upstream: Upstream) -> None:
    assert not hook_ok(cfg, upstream.path, "demo")
    assert install_hook(cfg, upstream.path, "demo") is None
    hook = upstream.path / ".git" / "hooks" / "post-merge"
    assert hook.stat().st_mode & 0o111
    assert hook_ok(cfg, upstream.path, "demo")


@pytest.mark.parametrize("other", ["dem", "demo2", "other"])
def test_hook_for_another_plugin_is_stale(cfg: Config, upstream: Upstream, other: str) -> None:
    assert install_hook(cfg, upstream.path, "demo") is None
    assert not hook_ok(cfg, upstream.path, other)
    assert install_hook(cfg, upstream.path, other) is None
    assert hook_ok(cfg, upstream.path, other)


@pytest.mark.parametrize("hooks_path", ["{tmp}/global-hooks", "../shared-hooks", "hooks"])
def test_no_hook_under_core_hookspath(
    cfg: Config, upstream: Upstream, tmp_path: Path, hooks_path: str
) -> None:
    # A hooks directory outside .git is shared: the tripwire would run in every
    # repository using it, and would replace whatever hook is already there.
    git(upstream.path, "config", "core.hooksPath", hooks_path.format(tmp=tmp_path))
    problem = install_hook(cfg, upstream.path, "demo")
    assert problem is not None
    assert problem.startswith("core.hooksPath is set (")
    assert problem.endswith("), so the tripwire was not installed")
    assert hook_target(upstream.path) == (None, problem)
    assert not hook_ok(cfg, upstream.path, "demo")
    assert not list(tmp_path.rglob("post-merge"))


def test_hook_under_core_hookspath_inside_git_dir(cfg: Config, upstream: Upstream) -> None:
    git(upstream.path, "config", "core.hooksPath", ".git/my-hooks")
    assert install_hook(cfg, upstream.path, "demo") is None
    assert (upstream.path / ".git" / "my-hooks" / "post-merge").is_file()
    assert hook_ok(cfg, upstream.path, "demo")


@pytest.mark.parametrize("kind", ["file", "symlink", "directory"])
def test_foreign_hook_is_left_alone(
    cfg: Config, upstream: Upstream, tmp_path: Path, kind: str
) -> None:
    hook = upstream.path / ".git" / "hooks" / "post-merge"
    hook.parent.mkdir(exist_ok=True)
    mine = "#!/bin/sh\necho my own hook\n"
    match kind:
        case "file":
            hook.write_text(mine)
        case "symlink":
            (tmp_path / "mine").write_text(mine)
            hook.symlink_to(tmp_path / "mine")
        case _:
            hook.mkdir()
    problem = install_hook(cfg, upstream.path, "demo")
    assert problem == f"a post-merge hook of your own exists at {hook.parent.resolve() / hook.name}"
    assert not hook_ok(cfg, upstream.path, "demo")
    if kind != "directory":
        assert hook.read_text() == mine
    assert hook.is_symlink() == (kind == "symlink")


def test_hook_from_an_earlier_release_is_replaced(cfg: Config, upstream: Upstream) -> None:
    hook = upstream.path / ".git" / "hooks" / "post-merge"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(f'#!/usr/bin/env bash\nexec "{cfg.self_path}" _post-merge "$top"\n')
    assert install_hook(cfg, upstream.path, "demo") is None
    assert hook_ok(cfg, upstream.path, "demo")


@pytest.mark.parametrize("override", [Overrides(root="/elsewhere"), Overrides(state="/elsewhere")])
def test_hook_with_other_paths_is_stale(
    cfg: Config, upstream: Upstream, tmp_path: Path, override: Overrides
) -> None:
    assert install_hook(cfg, upstream.path, "demo") is None
    env = {
        "HOME": str(tmp_path / "home"),
        "OMARCHY_PLUGIN_GATE_ROOT": str(cfg.root),
        "OMARCHY_PLUGIN_GATE_STATE": str(cfg.state_root),
    }
    other = Config.from_env(env, cfg.self_path, override)
    assert not hook_ok(other, upstream.path, "demo")


def test_hooks_without_paths_are_stale(cfg: Config, upstream: Upstream) -> None:
    hook = upstream.path / ".git" / "hooks" / "post-merge"
    hook.write_text(
        "#!/usr/bin/env bash\n"
        "top=$(git rev-parse --show-toplevel 2>/dev/null || pwd)\n"
        f'exec "{cfg.self_path}" _post-merge "$top" >>"{cfg.state_root}/hooks.log" 2>&1\n'
    )
    assert not hook_ok(cfg, upstream.path, "demo")


def test_hooks_without_a_plugin_name_are_stale(cfg: Config, upstream: Upstream) -> None:
    # The format written before hooks named their plugin.
    hook = upstream.path / ".git" / "hooks" / "post-merge"
    hook.write_text(
        "#!/usr/bin/env bash\n"
        "top=$(git rev-parse --show-toplevel 2>/dev/null || pwd)\n"
        f"exec {cfg.self_path} --root {cfg.root} --state {cfg.state_root} _post-merge "
        f'"$top" >>{cfg.state_root}/hooks.log 2>&1\n'
    )
    assert not hook_ok(cfg, upstream.path, "demo")


@pytest.mark.parametrize("present", [True, False])
def test_doctor_reports_omarchy(
    ctx: Context,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    present: bool,
) -> None:
    ctx.cfg.root.mkdir(parents=True)
    monkeypatch.setattr(
        doctor.proc,
        "which",
        lambda name: None if name == "omarchy" and not present else f"/stub/{name}",
    )
    doctor.run(ctx, "", fix=False)
    out = capsys.readouterr().out
    if present:
        assert "omarchy: /stub/omarchy" in out
    else:
        assert "omarchy is not on PATH; every candidate fails validation" in out


def test_post_merge_needs_a_name_and_a_directory(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(LAUNCHER, ["--root", "/r", "_post-merge", "/x"]) == 1
    assert "_post-merge needs a plugin name and a directory" in capsys.readouterr().err
