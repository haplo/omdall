# omdall

*omdall* is a Heimdall for your [Omarchy plugins](https://plugins.omarchy.org/):
every plugin is reviewed by an AI model before it is installed, and again
before every update.

Omarchy plugins run unsandboxed inside your session (`omarchy-shell`), with
full access to your user account. A plain `omarchy plugin update` pulls
whatever upstream published, so one malicious commit is enough to take over
your machine.

omdall puts a review step in between. It fetches plugin changes, checks them,
and has a read-only model review them. Your installed plugin only moves to a
commit that passed.

## Requirements

- Omarchy, with the `omarchy` command on `PATH`
- `python3` 3.14 or newer and `git` (standard library only, nothing to
  `pip install`)
- [OpenCode](https://opencode.ai), set up with a model

## Install

```sh
git clone https://github.com/haplo/omdall ~/Work/omdall
cd ~/Work/omdall
mise trust
mise run install
```

This links the `omdall` command into `~/.local/bin`, installs the reviewer
agent for OpenCode, writes an example config, and enables a daily check. Run
`omdall doctor --fix` afterwards to protect plugins you have already cloned.
See [docs/install.md](docs/install.md) for details, shell completions and
uninstalling.

## Quick start

```sh
omdall add https://github.com/ninepointlabs/omasync  # clone, review, install
omdall adopt <id>         # guard a plugin installed with omarchy plugin add
omdall check              # review upstream changes (the daily timer does this)
omdall update             # install approved changes
omdall status             # installed, approved, upstream, held back
omdall reviews <name>     # past reviews and their evidence
omdall approve <name>     # accept one failed commit after reading it yourself
```

You get a desktop notification only when you need to act: an update is ready,
or a review failed.

## How it works

```
~/Work/omarchy-plugins/<name>/     clone of upstream, owned by you
  refs/heads/gate-approved         last commit that passed review

~/.config/omarchy/plugins/<id>/    installed copy, origin = the clone above
```

The installed copy fetches from the local clone, not from upstream, so
`omarchy plugin update` can't skip the review. `check` reviews what upstream
added since `gate-approved` and moves `gate-approved` forward only when the
review passes. `update` then moves the installed copy to it.

Each review runs in two stages: structural checks without a model, then a model
review that must account for everything the checks flagged. Anything unclear
counts as a failure. See [docs/review.md](docs/review.md).

## Limits

- The model review is a second opinion, not proof. A hostile change may try to
  talk it into a pass. Reviews that cleared findings are marked, so read those
  first. When a review fails, read the diff before you approve it.
- Anyone who can write to your home directory can move `gate-approved`.
- Plugins still run unsandboxed. omdall reviews code before it runs; it does
  not limit what the code can do.

## Documentation

- [Installing](docs/install.md): setup, shell completions, uninstalling
- [Usage](docs/usage.md): each command, including adopting plugins you
  already have
- [Approving a failed review](docs/approving.md)
- [How it works](docs/how-it-works.md): layout, evidence, locking, tripwire
- [The review](docs/review.md): structural checks and the model reviewer
- [Configuration](docs/configuration.md): every setting
- [Scripting](docs/scripting.md): JSON output, activity.json, front ends and
  exit status
- [Development](docs/development.md): tools and tests

## License

[MIT](LICENSE).
