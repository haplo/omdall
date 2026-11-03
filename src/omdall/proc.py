"""The one place that runs external commands.

Every call takes a fixed argument list, never a shell. A non-zero exit raises
CommandError unless the caller says it expects one with check=False.
"""

import contextlib
import os
import shutil
import signal
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

# Variables git sets for hooks and `git -c`. Left in place they would point
# `git -C <dir>` at another repository, so no child process inherits them.
_GIT_LOCAL_VARS = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CONFIG",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_COUNT",
        "GIT_OBJECT_DIRECTORY",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_GRAFT_FILE",
        "GIT_INDEX_FILE",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_REPLACE_REF_BASE",
        "GIT_PREFIX",
        "GIT_SHALLOW_FILE",
        "GIT_COMMON_DIR",
    }
)


def child_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in _GIT_LOCAL_VARS and not k.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    if extra:
        env.update(extra)
    return env


@dataclass(frozen=True, slots=True)
class Result:
    argv: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def error(self) -> str:
        """The last line git or a tool printed to stderr, for a one-line warning."""
        lines = os.fsdecode(self.stderr).strip().splitlines()
        return lines[-1].strip() if lines else ""

    @property
    def text(self) -> str:
        """stdout without the trailing newline, undecodable bytes kept as escapes."""
        return os.fsdecode(self.stdout).rstrip("\n")


class CommandError(Exception):
    def __init__(self, result: Result) -> None:
        self.result = result
        tail = f": {result.error}" if result.error else ""
        super().__init__(f"{' '.join(result.argv[:4])} failed (exit {result.returncode}){tail}")


def which(name: str) -> str | None:
    return shutil.which(name)


def run(
    argv: Sequence[str],
    *,
    check: bool = True,
    cwd: Path | None = None,
    input: bytes | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    stdout: int | IO[bytes] = subprocess.PIPE,
    stderr: int | IO[bytes] = subprocess.PIPE,
) -> Result:
    args = tuple(argv)
    try:
        cp = subprocess.run(
            args,
            cwd=cwd,
            input=input,
            stdin=None if input is not None else subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            env=child_env(env),
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        result = Result(args, 127, b"", str(e).encode())
    else:
        result = Result(args, cp.returncode, cp.stdout or b"", cp.stderr or b"")
    if check and not result.ok:
        raise CommandError(result)
    return result


def run_quiet(argv: Sequence[str], *, cwd: Path | None = None) -> bool:
    """Run for the side effect only; True on success. Output is discarded."""
    try:
        return run(
            argv, check=False, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).ok
    except OSError:
        return False


@dataclass(frozen=True, slots=True)
class Supervised:
    returncode: int
    timed_out: bool


def run_supervised(
    argv: Sequence[str], *, cwd: Path, output: IO[bytes], timeout: float, grace: float = 5.0
) -> Supervised:
    """Run with stdout and stderr into `output`, killing the whole process group on timeout.

    The child gets its own session, so anything it spawns is killed with it.
    """
    try:
        child = subprocess.Popen(
            tuple(argv),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            env=child_env(),
            start_new_session=True,
        )
    except FileNotFoundError as e:
        output.write(f"{e}\n".encode())
        return Supervised(127, False)
    try:
        return Supervised(child.wait(timeout=timeout), False)
    except subprocess.TimeoutExpired:
        _kill_group(child, signal.SIGTERM)
        try:
            child.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            _kill_group(child, signal.SIGKILL)
            child.wait()
        return Supervised(124, True)
    finally:
        # A clean exit can still leave background children behind.
        _kill_group(child, signal.SIGKILL)


def _kill_group(child: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(child.pid, sig)
