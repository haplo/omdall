# How it works

## Layout

```
~/Work/omarchy-plugins/<name>/     clone, origin = upstream
  main                             your checkout; branch and push as usual
  refs/heads/gate-approved         last commit that passed review or was approved

~/.config/omarchy/plugins/<id>/    installed copy, origin = the clone above
```

The installed copy fetches from the clone, so a plain `omarchy plugin update`
only sees the clone's `main`: approved commits or your own work, never
upstream directly.

- `check` fetches upstream, reviews `gate-approved..origin/<branch>`, and moves
  `gate-approved` forward if the review passes.
- `update` fast-forwards the installed copy to `gate-approved`, validates the
  manifest, and makes the shell rescan.

`gate-approved` only moves from the commit the run started from, so it can't
skip over a change made by someone else in the meantime.

## Evidence

Each plugin keeps its records in `~/.local/state/omdall/<name>/`:

```
reviews/<short-sha>/patch         the diff that was reviewed
reviews/<short-sha>/patch.review  the copy given to the reviewer, with a code word
reviews/<short-sha>/mech.txt      hard structural check results
reviews/<short-sha>/findings.txt  findings given to the reviewer
reviews/<short-sha>/hints.txt     keyword hints given to the reviewer
reviews/<short-sha>/review.txt    the reviewer's full output
reviews/<short-sha>/verdict       REVIEW PASS or FAIL, with reasons
reviews/<short-sha>/cleared       findings the reviewer cleared, and why
reviewed/<sha>                    approval from a passed review
waived/<sha>                      approval by hand (see approving.md)
held                              the last commit held back, and why
adopted                           adopt: date, user, previous origin
```

All evidence files are written before a decision is made, whatever the
outcome.

## Locking

`add`, `adopt`, `approve`, `check`, `update`, `doctor --fix` and the tripwire
take a lock (`gate.lock` in the state directory), so they never write at the
same time. A second run prints `waiting for another run to finish…` and
waits. With `--no-wait` it exits with status 75 instead, without doing
anything. `status`, `reviews`, `doctor` and `approve --dry-run` never wait.

The daily check and the tripwire always wait, so a busy lock never makes them
skip a review.

Each run that holds the lock writes what it is doing to `activity.json` in
the state directory, so a front end can show progress whoever started the
run. See [Scripting](scripting.md#activityjson).

## Tripwire

The tripwire is a `post-merge` git hook, installed in both the clone and the
installed copy by `doctor --fix` (and by `check`, `approve` and `update`). It
catches merges that bypassed the gate, such as a manual `git pull`. It reviews
the incoming upstream commits. If the review fails, it rolls them back and
disables the plugin. Commits you made yourself are never reviewed or rolled
back.

The rollback uses `git reset --keep`, which keeps your uncommitted changes. If
rolling back would overwrite one of them, the hook leaves the merge in place.
It disables the plugin, logs `could not roll back`, and notifies you, so you
can sort it out by hand. `update` rolls back a failed merge the same way.

Each hook knows its plugin, and finds the installed copy by the id in the
approved commit, so changing the manifest id can't get a merge past it. The
hook also records the root and state directories it was installed with, so it
uses the same clones and evidence whatever environment `git pull` runs in.
`check`, `approve` and `update` rewrite hooks that name a different plugin,
root or state, or that come from an older release.

omdall only writes hooks into the repository's own git directory, and only
replaces hooks it wrote itself. If `core.hooksPath` points somewhere else, or
you have your own `post-merge` hook, no tripwire is installed and `doctor`
reports the problem. Unset `core.hooksPath` for that repository or move your
hook aside, then run `doctor --fix`.

The tripwire is a safety net, not the gate: the shell may have reloaded the
plugin before the hook finishes. The gate is what keeps bad code out.
