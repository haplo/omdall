import pytest

from omdall import proc
from omdall.notify import PANEL_TARGET, CheckSummary, check_notification, click_action


def summary(**kw: list[str]) -> CheckSummary:
    return CheckSummary(**kw)


def test_quiet_when_nothing_happened() -> None:
    assert check_notification(summary(), "all") is None


def test_single_ready() -> None:
    assert check_notification(summary(ready=["demo"]), "all") == (
        "demo: update ready",
        "Reviewed and approved. Run omdall update.",
    )


def test_single_ready_with_cleared_findings() -> None:
    message = check_notification(summary(ready=["demo"], cleared=["demo"]), "all")
    assert message is not None
    assert message[1].startswith("Approved after the reviewer cleared structural findings.")


def test_single_held() -> None:
    assert check_notification(summary(held=["demo"]), "all") == (
        "demo: update held back",
        "The review failed. Open status to see why.",
    )


def test_many() -> None:
    s = summary(ready=["a", "b"], held=["c"], errors=["d"], cleared=["a"])
    assert check_notification(s, "all") == (
        "3 plugin updates reviewed",
        "2 ready to install · 1 held back · 1 with cleared findings · 1 error(s)",
    )


@pytest.mark.parametrize(
    ("s", "expected"),
    [(summary(held=["x"]), False), (summary(ready=["x"]), True), (summary(errors=["x"]), False)],
)
def test_ready_policy(s: CheckSummary, expected: bool) -> None:
    assert (check_notification(s, "ready") is not None) is expected


def test_none_policy() -> None:
    assert check_notification(summary(ready=["x"]), "none") is None


def test_click_opens_a_terminal_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(proc, "which", lambda name: f"/stub/{name}")
    assert click_action("terminal") == [
        "omarchy-launch-floating-terminal-with-presentation",
        "omdall status",
    ]


def test_click_opens_the_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(proc, "which", lambda name: f"/stub/{name}")
    assert PANEL_TARGET == "net.fidelramos.omdall"
    assert click_action("panel") == ["omarchy-shell", "net.fidelramos.omdall", "open"]


def test_panel_falls_back_without_omarchy_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(proc, "which", lambda name: None if name == "omarchy-shell" else name)
    assert click_action("panel") == click_action("terminal")
