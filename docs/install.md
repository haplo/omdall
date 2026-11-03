# Installing

```sh
git clone https://github.com/haplo/omdall ~/Work/omdall
cd ~/Work/omdall
mise trust
mise run install
```

Without mise, run [`scripts/install.sh`](../scripts/install.sh). Install does
the following:

1. Links the `omdall` command into `~/.local/bin`.
2. Links shell completions into `~/.local/share`.
3. Installs the reviewer agent as `~/.config/opencode/agents/omdall-reviewer.md`.
4. Copies [`config.example.toml`](../config.example.toml) to
   `~/.config/omdall/config.toml`, unless a config file already exists.
5. Installs the systemd user units and enables the daily `check`.
   `mise run install:no-timer` skips the timer.

Running it again is safe. Run it again after pulling a change to the reviewer
agent: `omdall doctor` reports an installed agent that no longer matches.

Then add tripwires to plugins you have already cloned:

```sh
omdall doctor --fix
```

## Shell completions

Completions for bash, zsh and fish are linked into `$XDG_DATA_HOME`
(`~/.local/share` by default):

| Shell | Path |
|---|---|
| bash | `bash-completion/completions/omdall` |
| fish | `fish/vendor_completions.d/omdall.fish` |
| zsh | `zsh/site-functions/_omdall` |

bash and fish find them automatically. zsh needs this in `~/.zshrc`, before
`compinit`:

```sh
fpath=(~/.local/share/zsh/site-functions $fpath)
```

They complete commands, options, plugin names, and the held commit for
`approve --sha`. They follow `--root`, `--state`, the environment and the
config file, just like the command does.

## Uninstalling

```sh
mise run uninstall
```

This removes the command, the reviewer agent, the completions, the systemd
units and the tripwire hooks. Your config file, clones, review evidence and
installed plugins stay. The output explains how to point installed plugins back
at their upstream repositories.
