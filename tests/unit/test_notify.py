import pytest

from omdall.notify import CheckSummary, check_notification


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
