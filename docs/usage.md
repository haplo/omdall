# Usage

`omdall --help` gives the exact syntax. This page explains what each command
does.

## add

```sh
omdall add https://github.com/ninepointlabs/omasync
```

Clones the plugin into the gate root (`~/Work/omarchy-plugins/<name>`),
reviews the whole tree, installs it disabled, and enables it if the review
passes. `--dir NAME` picks the clone's directory name. `--no-enable` leaves the
plugin disabled. Run without a URL in a terminal, `add` asks for one.

If the review fails, the clone is kept and the commit is held back. You can
read it and [approve it by hand](approving.md), then run `update -p <name>` to
install it.

`add` only accepts URLs where the server proves who it is or the source is
local: `https://`, `ssh://`, `user@host:path`, `file://`, or an absolute path.
It refuses `http://` and `git://`, because anyone on the network could swap
the code. It also refuses transport helpers such as `ext::` and anything that
looks like an option. When `omarchy-git-url-check` is installed, the URL must
pass that check too.

`add` refuses a plugin that is already installed. To bring one you installed
with `omarchy plugin add` under the gate, use [`adopt`](#adopt) instead.

## check

Fetches upstream for each plugin and reviews any new commits. A commit that
passes becomes `gate-approved`. A commit that fails is held back. `check` never
touches the installed copy. The daily timer runs it.

`-p NAME` checks only one plugin.

`add`, `adopt`, `check`, `update` and `doctor` take `--json` for scripts and
front ends; see [Scripting](scripting.md).

## update

Moves each installed copy forward to `gate-approved`, validates the manifest,
and makes the shell rescan its plugins. `-p NAME` updates one plugin. If that
plugin was approved but never installed, `update -p` installs and enables it.

`update` refuses an installed copy that has modified, staged or untracked
files, and lists them: nobody reviewed those. Commit them, remove them or
`git checkout` them first. Ignored files, such as a plugin's cache, don't count.

## status

Shows, for each plugin, the installed, approved and upstream commits, any
held-back commit, and the command to run next. It also flags local changes in
the installed copy and an installed commit that was never reviewed.

## reviews

Lists recorded reviews, newest first: verdict, reasons, findings, how the
commit was approved, and where the evidence lives.

## doctor

Checks the wiring: hooks, each installed copy's origin, refs, the reviewer
agent and model, an `omarchy` command on `PATH`, and clones that fetch over
`http://` or `git://`. It also checks that each installed copy is on a
reviewed commit with no local changes. `--fix` installs missing hooks.

## adopt

```sh
omdall adopt acme.weather
omdall adopt acme.weather --url https://github.com/acme/omarchy-weather
```

Brings a plugin you installed with `omarchy plugin add` under the gate. Until
then it fetches straight from upstream, and a plain `omarchy plugin update`
skips the review. `adopt <id>`:

1. clones the installed copy's origin, or `--url`, into the gate root
   (`--dir NAME` picks the name, as for `add`);
2. checks that the clone is the same plugin id, and removes it if not;
3. points the installed copy's origin at the clone, and records the previous
   origin in `~/.local/state/omdall/<name>/adopted`;
4. reviews upstream's current commit, as `check` does for a new clone, and
   installs the tripwires.

The installed copy keeps its files and the commit it is on, and stays
enabled. Only `update` moves it. If it is on a different commit than the one
that was reviewed, `status` and `doctor` report it as never reviewed until you
run `update`.

If the review fails, the plugin stays installed and enabled, pointed at the
clone, with the commit held back. You can [approve it by
hand](approving.md), or disable it with `omarchy plugin disable <id>`. If
something goes wrong before the review starts, `adopt` puts the origin back
and removes the clone.

`omdall status --json` lists the installed plugins that are not guarded under
`unguarded`, with the reason when `adopt` cannot take one as it is. The URL
must pass the same checks as for `add`. You need `--url` when the installed
copy has no origin, when its origin is a path on this machine, or when it is
not a git checkout at all. In that last case `adopt` makes the installed
directory a checkout of the clone's commit without touching its files, so any
file that differs from upstream shows up as a local change.
