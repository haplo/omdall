"""Desktop notifications. One at a time: each replaces the last."""

from dataclasses import dataclass, field

from . import proc
from .context import Context
from .state import write_atomic

APP = "omdall"
ICON = "󰕥"

# The front-end shell plugin's id, which is also its IPC target. With
# notify-action = "panel", a click on a notification opens its panel.
PANEL_TARGET = "net.fidelramos.omdall"


def click_action(action: str) -> list[str]:
    """What a click on a notification runs. The panel needs omarchy-shell; without
    it the click opens status in a terminal, as by default."""
    if action == "panel" and proc.which("omarchy-shell"):
        return ["omarchy-shell", PANEL_TARGET, "open"]
    return ["omarchy-launch-floating-terminal-with-presentation", "omdall status"]


def notify(ctx: Context, headline: str, body: str) -> None:
    if ctx.cfg.notify_policy == "none" or proc.which("omarchy-notification-send") is None:
        return
    if headline.startswith("-"):
        headline = f" {headline}"
    argv = [
        "omarchy-notification-send",
        "--app-name",
        APP,
        "-g",
        ICON,
        "-u",
        "normal",
        "-t",
        "30000",
        "-r",
        str(ctx.state.notify_id()),
        "-p",
        headline,
        body,
        "--exec",
        *click_action(ctx.cfg.notify_action),
    ]
    result = proc.run(argv, check=False)
    new_id = result.text.strip()
    if result.ok and new_id.isascii() and new_id.isdigit():
        write_atomic(ctx.state.notify_id_file, new_id)


def notify_close(ctx: Context) -> None:
    nid = ctx.state.notify_id()
    if nid:
        proc.run_quiet(
            [
                "busctl",
                "--user",
                "call",
                "org.freedesktop.Notifications",
                "/org/freedesktop/Notifications",
                "org.freedesktop.Notifications",
                "CloseNotification",
                "u",
                str(nid),
            ]
        )
    ctx.state.notify_id_file.unlink(missing_ok=True)


@dataclass(slots=True)
class CheckSummary:
    ready: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cleared: list[str] = field(default_factory=list)


def check_notification(s: CheckSummary, policy: str) -> tuple[str, str] | None:
    """The notification a check run deserves under `policy`, if any."""
    ready, held, errors, cleared = len(s.ready), len(s.held), len(s.errors), len(s.cleared)
    if ready + held + errors == 0 or policy == "none":
        return None
    if policy == "ready" and ready == 0:
        return None
    if ready + held == 1 and errors == 0:
        if ready == 1:
            name = s.ready[0]
            if name in s.cleared:
                body = (
                    "Approved after the reviewer cleared structural findings. "
                    "Check status, then run omdall update."
                )
            else:
                body = "Reviewed and approved. Run omdall update."
            return f"{name}: update ready", body
        return f"{s.held[0]}: update held back", "The review failed. Open status to see why."
    body = f"{ready} ready to install · {held} held back"
    if cleared:
        body += f" · {cleared} with cleared findings"
    if errors:
        body += f" · {errors} error(s)"
    return f"{ready + held} plugin updates reviewed", body
