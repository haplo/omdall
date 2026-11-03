"""activity.json: the change signal and live progress a front end watches."""

import json
from pathlib import Path

import pytest

from omdall import cli, proc
from omdall.activity import Activity, for_status
from omdall.commands import check
from omdall.context import Context
from omdall.notify import CheckSummary
from omdall.output import GateError
from omdall.results import PluginResult, Report
from test_state import hold_lock, release

LAUNCHER = Path(__file__).parents[2] / "bin" / "omdall"


def read(ctx: Context) -> dict:
    return json.loads(ctx.activity.path.read_text())


def gate_args(ctx: Context, *argv: str) -> list[str]:
    return ["--root", str(ctx.cfg.root), "--state", str(ctx.state.root), *argv]


def test_start_progress_finish(ctx: Context) -> None:
    ctx.activity.start("check")
    data = read(ctx)
    assert data["schema"] == 1
    running = data["running"]
    assert (running["command"], running["phase"], running["plugin"]) == ("check", None, None)
    assert data["last_run"] is None
    first = data["seq"]

    ctx.progress("fetching", "demo", 1, 2)
    ctx.progress("reviewing", "demo")
    data = read(ctx)
    running = data["running"]
    assert (running["phase"], running["plugin"], running["index"], running["total"]) == (
        "reviewing",
        "demo",
        1,
        2,
    )
    assert running["timeout"] == ctx.cfg.review_timeout
    assert data["seq"] == first + 2

    ctx.progress("checking", "other")
    running = read(ctx)["running"]
    assert (running["index"], running["total"], running["timeout"]) == (None, None, None)

    ctx.activity.finish(0, CheckSummary(ready=["demo"]))
    data = read(ctx)
    assert data["running"] is None
    assert data["last_run"]["command"] == "check"
    assert data["last_run"]["exit"] == 0
    assert data["last_run"]["summary"]["ready"] == ["demo"]
    assert data["last_check"]["summary"]["ready"] == ["demo"]
    assert data["seq"] == first + 4


def test_repeated_progress_is_not_rewritten(ctx: Context) -> None:
    ctx.activity.start("update")
    ctx.progress("installing", "demo", 1, 1)
    seq = read(ctx)["seq"]
    ctx.progress("installing", "demo")
    assert read(ctx)["seq"] == seq


def test_progress_outside_a_run_writes_nothing(ctx: Context) -> None:
    ctx.progress("fetching", "demo")
    ctx.activity.finish(0)
    assert not ctx.activity.path.exists()


def test_unknown_phase_is_a_bug(ctx: Context) -> None:
    ctx.activity.start("check")
    with pytest.raises(ValueError, match="unknown activity phase"):
        ctx.progress("sleeping")


def test_last_check_survives_other_commands(ctx: Context) -> None:
    ctx.activity.start("check")
    ctx.activity.finish(0, CheckSummary(held=["demo"]))
    ctx.activity.start("update")
    ctx.activity.finish(0)
    data = read(ctx)
    assert data["last_run"]["command"] == "update"
    assert data["last_check"]["summary"]["held"] == ["demo"]


def test_a_broken_file_is_replaced(ctx: Context) -> None:
    ctx.state.root.mkdir(parents=True)
    ctx.activity.path.write_text("{not json")
    ctx.activity.start("check")
    assert read(ctx)["seq"] == 1


def test_an_unwritable_file_never_fails_the_run(ctx: Context) -> None:
    ctx.state.root.mkdir(parents=True)
    ctx.activity.path.mkdir()
    ctx.activity.start("check")
    ctx.activity.finish(0)


def test_status_hides_a_stale_run() -> None:
    data = {"seq": 3, "running": {"command": "check"}}
    assert for_status(data, busy=False) == {"seq": 3, "running": None}
    assert for_status(data, busy=True) == data
    assert for_status(None, busy=True) is None


@pytest.mark.parametrize(
    ("raised", "exit_code"), [(GateError("no"), 1), (KeyboardInterrupt(), 130), (OSError(), 1)]
)
def test_locked_run_is_cleared_however_it_ends(
    ctx: Context, raised: BaseException, exit_code: int
) -> None:
    with pytest.raises(type(raised)), cli._locked(ctx, "check"):
        assert read(ctx)["running"]["command"] == "check"
        raise raised
    data = read(ctx)
    assert data["running"] is None
    assert data["last_run"]["exit"] == exit_code


def test_locked_run_records_the_report(ctx: Context) -> None:
    with cli._locked(ctx, "check") as run:
        run.done(Report("check", 0, [], CheckSummary(ready=["demo"])))
    assert read(ctx)["last_check"]["summary"]["ready"] == ["demo"]


@pytest.mark.parametrize(
    "argv",
    [["check"], ["update"], ["doctor", "--fix"], ["approve", "demo", "--reason", "x"]],
)
def test_every_locked_command_publishes_its_run(
    ctx: Context, argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx.cfg.root.mkdir(parents=True)
    monkeypatch.setattr(proc, "which", lambda _name: None)
    cli.main(LAUNCHER, gate_args(ctx, *argv))
    data = read(ctx)
    assert data["running"] is None
    assert data["last_run"]["command"] == argv[0]
    assert data["seq"] >= 2


@pytest.mark.parametrize(
    "argv",
    [["status"], ["status", "--json"], ["reviews"], ["doctor"], ["approve", "demo", "-n"]],
)
def test_read_only_commands_leave_it_alone(
    ctx: Context, argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx.cfg.root.mkdir(parents=True)
    monkeypatch.setattr(proc, "which", lambda _name: None)
    cli.main(LAUNCHER, gate_args(ctx, *argv))
    assert not ctx.activity.path.exists()


def test_busy_run_writes_nothing(ctx: Context) -> None:
    ctx.cfg.root.mkdir(parents=True)
    holder = hold_lock(ctx)
    try:
        assert cli.main(LAUNCHER, gate_args(ctx, "check", "--no-wait")) == 75
    finally:
        release(holder)
    assert not ctx.activity.path.exists()


def test_check_reports_each_plugin(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    phases: list[tuple[str, str | None, int | None, int | None]] = []
    for name in ("a", "b"):
        (ctx.cfg.root / name).mkdir(parents=True)
        (ctx.cfg.root / name / "manifest.json").write_text("{}")
    monkeypatch.setattr(
        Activity,
        "progress",
        lambda _self, phase, plugin, i, n, _t: phases.append((phase, plugin, i, n)),
    )
    report = check.run(ctx, "")
    assert phases == [("fetching", "a", 1, 2), ("fetching", "b", 2, 2)]
    assert [r.outcome for r in report.results if isinstance(r, PluginResult)] == ["error", "error"]
