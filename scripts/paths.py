"""Print the gate root and state directory, one per line, for the shell scripts.

Resolved by the gate's own settings code, so the environment and the config file
apply exactly as they do for the command. Run with `python3 -I`.
"""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from omdall.config import Config  # noqa: E402
from omdall.output import GateError  # noqa: E402

try:
    cfg = Config.from_env(os.environ, REPO / "bin" / "omdall")
except GateError as e:
    sys.exit(f"omdall: {e}")
print(cfg.root)
print(cfg.state_root)
