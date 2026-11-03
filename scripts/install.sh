#!/usr/bin/env bash
# Install omdall for the current user.
#
# Symlinks the command into ~/.local/bin, installs the reviewer agent and the
# systemd user units, copies the example config if there is none, and enables
# the nightly check. Idempotent: run it again after pulling changes.

set -euo pipefail

REPO=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)

BIN_DIR=${OMDALL_BIN_DIR:-$HOME/.local/bin}
CONFIG_HOME=${XDG_CONFIG_HOME:-}
[[ $CONFIG_HOME == /* ]] || CONFIG_HOME=$HOME/.config
DATA_HOME=${XDG_DATA_HOME:-}
[[ $DATA_HOME == /* ]] || DATA_HOME=$HOME/.local/share
CONFIG_FILE=$CONFIG_HOME/omdall/config.toml
UNIT_DIR=$CONFIG_HOME/systemd/user
AGENT_FILE=$CONFIG_HOME/opencode/agents/omdall-reviewer.md
BASH_COMPLETION_DIR=$DATA_HOME/bash-completion/completions
FISH_COMPLETION_DIR=$DATA_HOME/fish/vendor_completions.d
ZSH_COMPLETION_DIR=$DATA_HOME/zsh/site-functions
ENABLE_TIMER=1

usage() {
  cat <<'EOF'
Install omdall for the current user.

Usage: scripts/install.sh [--no-timer]

  --no-timer   install the command and agent, but do not enable the nightly check

Environment:
  OMDALL_BIN_DIR    where to link the command (default ~/.local/bin)
  OMDALL_STATE      state directory (default: from the config file, or
                    ~/.local/state/omdall)
  XDG_CONFIG_HOME   config root (default ~/.config)
  XDG_DATA_HOME     where shell completions are linked (default
                    ~/.local/share)

An existing config file is never overwritten.
EOF
}

while (($# > 0)); do
  case $1 in
  --no-timer) ENABLE_TIMER=0; shift ;;
  -h | --help) usage; exit 0 ;;
  *)
    echo "install: unknown option: $1" >&2
    exit 1
    ;;
  esac
done

command -v git >/dev/null 2>&1 || { echo "install: git is required" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "install: python3 is required" >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 14))' ||
  { echo "install: python 3.14 or newer is required (found $(python3 -V 2>&1))" >&2; exit 1; }
[[ -f $REPO/bin/omdall ]] || { echo "install: missing $REPO/bin/omdall" >&2; exit 1; }
for file in omdall.bash omdall.fish _omdall; do
  [[ -f $REPO/completions/$file ]] || { echo "install: missing $REPO/completions/$file" >&2; exit 1; }
done

if [[ -e $CONFIG_FILE || -L $CONFIG_FILE ]]; then
  CONFIG_NOTE="kept"
else
  mkdir -p "$(dirname "$CONFIG_FILE")"
  cp "$REPO/config.example.toml" "$CONFIG_FILE"
  CONFIG_NOTE="created, every setting at its default"
fi

# The state directory may be set in the config file, so ask the gate.
paths=$(python3 -I "$REPO/scripts/paths.py") || exit 1
STATE_DIR=$(sed -n 2p <<<"$paths")

mkdir -p "$BIN_DIR" "$STATE_DIR" "$UNIT_DIR" "$(dirname "$AGENT_FILE")"
mkdir -p "$BASH_COMPLETION_DIR" "$FISH_COMPLETION_DIR" "$ZSH_COMPLETION_DIR"

if [[ -e $BIN_DIR/omdall && ! -L $BIN_DIR/omdall ]]; then
  echo "install: replacing the existing copy at $BIN_DIR/omdall"
fi
chmod 755 "$REPO/bin/omdall"
ln -sfn "$REPO/bin/omdall" "$BIN_DIR/omdall"

# Linked, not copied, so a pull updates the completions too.
for target in "$BASH_COMPLETION_DIR/omdall" \
  "$FISH_COMPLETION_DIR/omdall.fish" \
  "$ZSH_COMPLETION_DIR/_omdall"; do
  if [[ -e $target && ! -L $target ]]; then
    echo "install: replacing the existing file at $target"
  fi
done
ln -sfn "$REPO/completions/omdall.bash" "$BASH_COMPLETION_DIR/omdall"
ln -sfn "$REPO/completions/omdall.fish" "$FISH_COMPLETION_DIR/omdall.fish"
ln -sfn "$REPO/completions/_omdall" "$ZSH_COMPLETION_DIR/_omdall"

# The agent's scope comes from the directory the gate runs it in, so the
# template is installed as is. Re-run this script after changing it.
cp "$REPO/agents/omdall-reviewer.md.in" "$AGENT_FILE"

for unit in omdall-check.service omdall-check.timer; do
  sed "s#%h/.local/bin/omdall#$BIN_DIR/omdall#g" \
    "$REPO/systemd/$unit" >"$UNIT_DIR/$unit"
done

if command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload >/dev/null 2>&1 || true
  if ((ENABLE_TIMER)); then
    systemctl --user enable --now omdall-check.timer
  fi
fi

cat <<EOF

omdall installed

  command   $BIN_DIR/omdall -> $REPO/bin/omdall
  config    $CONFIG_FILE ($CONFIG_NOTE)
  reviewer  $AGENT_FILE
  units     $UNIT_DIR/omdall-check.{service,timer}
  state     $STATE_DIR
  completions
            bash  $BASH_COMPLETION_DIR/omdall
            fish  $FISH_COMPLETION_DIR/omdall.fish
            zsh   $ZSH_COMPLETION_DIR/_omdall

Next:
  omdall doctor --fix      # add the review tripwire to existing clones
  omdall add <git-url>     # gate a new plugin
  omdall check             # review what is already cloned

zsh does not scan a per-user completion directory. Add this to ~/.zshrc, before
compinit, to use the zsh completion:
  fpath=($ZSH_COMPLETION_DIR \$fpath)

Optional, for a stronger reviewer model: set model = "venice/<model>" in the
config file. The nightly check reads it too.
EOF
