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
plugin disabled.

If the review fails, the clone is kept and the commit is held back. You can
read it and [approve it by hand](approving.md), then run `update -p <name>` to
install it.

`add` only accepts URLs where the server proves who it is or the source is
local: `https://`, `ssh://`, `user@host:path`, `file://`, or an absolute path.
It refuses `http://` and `git://`, because anyone on the network could swap
the code. It also refuses transport helpers such as `ext::` and anything that
looks like an option. When `omarchy-git-url-check` is installed, the URL must
pass that check too.

## check

Fetches upstream for each plugin and reviews any new commits. A commit that
passes becomes `gate-approved`. A commit that fails is held back. `check` never
touches the installed copy. The daily timer runs it.

`-p NAME` checks only one plugin.

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

## Adopting a plugin you already have

`add` refuses a plugin id that is already installed. To bring a plugin that
Omarchy installed from GitHub under the gate:

```sh
git clone <upstream-url> ~/Work/omarchy-plugins/<name>
git -C ~/.config/omarchy/plugins/<id> remote set-url origin ~/Work/omarchy-plugins/<name>
omdall check         # reviews the whole current tree
omdall doctor --fix  # installs the tripwires
```

The first review covers upstream's current commit. If your installed copy is
on a different commit, `status` and `doctor` report it as never reviewed until
you run `update`.
