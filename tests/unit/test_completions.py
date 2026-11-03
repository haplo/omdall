"""The shell completion scripts must not drift from the parser."""

import re
from pathlib import Path

import pytest

from omdall import cli
from omdall.commands import complete
from omdall.config import Config
from omdall.context import Context

LAUNCHER = Path(__file__).parents[2] / "bin" / "omdall"
COMPLETIONS = Path(__file__).parents[2] / "completions"
BASH = COMPLETIONS / "omdall.bash"
ZSH = COMPLETIONS / "_omdall"
FISH = COMPLETIONS / "omdall.fish"
SHELL_FILES = (BASH, ZSH, FISH)

# `add) flags+=(--dir --no-enable) ;;` in the bash and zsh scripts, including
# shared arms such as `check | update | status)`.
FLAG_BLOCK = re.compile(r"^  ([a-z]+(?: \| [a-z]+)*)\) flags\+=\(([^)]*)\)", re.MULTILINE)


def parser_flags(prog: str) -> set[str]:
    return {s for action in cli.command_parser(prog)._actions for s in action.option_strings}


def global_flags() -> set[str]:
    return set.intersection(*(parser_flags(cmd) for cmd in cli.COMMANDS))


def long_flags(text: str) -> set[str]:
    return set(re.findall(r"--[a-z][a-z-]*", text))


def mentioned_options(path: Path) -> set[str]:
    """Every long option the script mentions, in that shell's spelling."""
    text = path.read_text()
    if path == FISH:
        return {f"--{name}" for name in re.findall(r"-l ([a-z][a-z-]*)", text)}
    return long_flags(text)


def command_blocks(text: str) -> dict[str, set[str]]:
    blocks: dict[str, set[str]] = {}
    for commands, listed in FLAG_BLOCK.findall(text):
        for command in commands.split("|"):
            blocks[command.strip()] = set(listed.split())
    return blocks


@pytest.mark.parametrize("path", SHELL_FILES, ids=lambda p: p.name)
def test_every_command_is_completed(path: Path) -> None:
    text = path.read_text()
    for command in cli.COMMANDS:
        assert re.search(rf"(?<![\w-]){command}(?![\w-])", text), f"{command} in {path.name}"


@pytest.mark.parametrize("path", SHELL_FILES, ids=lambda p: p.name)
def test_every_option_is_completed(path: Path) -> None:
    """A new setting or command option must show up in every shell."""
    expected = {flag for cmd in cli.COMMANDS for flag in parser_flags(cmd) if flag.startswith("--")}
    assert expected - mentioned_options(path) == set()


@pytest.mark.parametrize("path", (BASH, ZSH), ids=lambda p: p.name)
def test_command_options_match_the_parser(path: Path) -> None:
    blocks = command_blocks(path.read_text())
    assert set(blocks) == set(cli.COMMANDS)
    shared = global_flags()
    for command in cli.COMMANDS:
        assert blocks[command] == parser_flags(command) - shared, f"{command} in {path.name}"


def test_fish_short_options() -> None:
    expected = {
        flag[1:]
        for flag in set().union(*(parser_flags(c) for c in cli.COMMANDS))
        if not flag.startswith("--")
    }
    assert set(re.findall(r"-s ([a-z])", FISH.read_text())) == expected


def make_plugin(cfg: Config, name: str, manifest_id: str = "") -> None:
    clone = cfg.root / name
    clone.mkdir(parents=True)
    (clone / "manifest.json").write_text(f'{{"id": "{manifest_id or name}"}}')


def test_complete_plugins(cfg: Config, ctx: Context, capsys: pytest.CaptureFixture[str]) -> None:
    make_plugin(cfg, "beta")
    make_plugin(cfg, "alpha")
    (cfg.root / ".hidden").mkdir()
    (cfg.root / "no-manifest").mkdir()
    assert complete.run(ctx, ["plugins"]) == 0
    assert capsys.readouterr().out.splitlines() == ["alpha", "beta"]


def test_complete_held_sha(cfg: Config, ctx: Context, capsys: pytest.CaptureFixture[str]) -> None:
    make_plugin(cfg, "demo", "selftest.demo")
    held = cfg.state_root / "demo" / "held"
    held.parent.mkdir(parents=True)
    held.write_text("0123456789abcdef0123456789abcdef01234567\nwhy\n")
    assert complete.run(ctx, ["held", "selftest.demo"]) == 0
    assert capsys.readouterr().out == "0123456789ab\n"


@pytest.mark.parametrize("args", [["held", "missing"], ["held"], ["nonsense"], []])
def test_complete_answers_nothing(
    args: list[str], cfg: Config, ctx: Context, capsys: pytest.CaptureFixture[str]
) -> None:
    make_plugin(cfg, "demo")
    assert complete.run(ctx, args) == 0
    assert capsys.readouterr().out == ""


def test_complete_is_silent_when_the_config_is_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "omdall" / "config.toml"
    config.parent.mkdir()
    config.write_text("modle = 'typo'\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert cli.main(LAUNCHER, ["_complete", "plugins"]) == 0
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")
