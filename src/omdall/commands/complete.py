"""_complete: what the shell completion scripts ask for.

Hidden and undocumented, like `_post-merge`, and deliberately plain: one
candidate per line on stdout, nothing on stderr, and it never raises. The
caller in `cli` turns any error into "no candidates" rather than an error
message inside the user's shell.
"""

from collections.abc import Sequence

from .. import plugins
from ..context import Context
from ..output import say
from ..state import one_line


def run(ctx: Context, args: Sequence[str]) -> int:
    kind = args[0] if args else ""
    match kind:
        case "plugins":
            for name in plugins.plugin_names(ctx.cfg):
                say(one_line(name))
        case "held" if len(args) > 1:
            names = [
                name
                for name in plugins.plugin_names(ctx.cfg)
                if args[1] in (name, plugins.manifest_id(ctx.cfg, name))
            ]
            held = ctx.state.held(names[0]) if names else None
            if held:
                say(held.sha[:12])
    return 0
