# Configuration

You can set each option in three places. From highest priority to lowest:

1. a command-line option, before or after the command
2. an environment variable
3. the config file

An empty value counts as unset.

```sh
omdall --model venice/claude-opus-4-7 check
omdall check -p omasync --timeout 900
```

## Config file

`$XDG_CONFIG_HOME/omdall/config.toml`, which defaults to
`~/.config/omdall/config.toml`:

```toml
model = "venice/claude-opus-4-7"
timeout = 900
```

Install copies [`config.example.toml`](../config.example.toml) here, with every
setting commented out at its default. It never overwrites an existing file.
A missing file is fine. Unknown keys, wrong types and invalid TOML are errors.
`timeout` and `max-patch` are integers and all other settings are strings.
`root` and `state` must be absolute or start with `~/`. The daily check reads
the same file.

## Settings

| Option | Variable | Key | Default | Purpose |
|---|---|---|---|---|
| `--root DIR` | `OMDALL_ROOT` | `root` | `~/Work/omarchy-plugins` | where clones live |
| `--state DIR` | `OMDALL_STATE` | `state` | `~/.local/state/omdall` | evidence and markers |
| `--agent NAME` | `OMDALL_AGENT` | `agent` | `omdall-reviewer` | OpenCode agent, from `~/.config/opencode/agents/<name>.md` |
| `--model ID` | `OMDALL_MODEL` | `model` | OpenCode's default | reviewer model, e.g. `venice/claude-opus-4-7` |
| `--notify POLICY` | `OMDALL_NOTIFY` | `notify` | `all` | `all`, `ready` or `none` |
| `--timeout SECONDS` | `OMDALL_TIMEOUT` | `timeout` | `420` | reviewer timeout |
| `--max-patch BYTES` | `OMDALL_MAX_PATCH` | `max-patch` | `2097152` | largest diff sent for review |

The `max-patch` default assumes a model with a 1M-token context. For a smaller
model, lower it to about 3 bytes per token, minus some headroom.

Tripwire hooks remember the root and state they were installed with. See
[How it works](how-it-works.md#tripwire).
