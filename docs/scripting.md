# Scripting

`--json` is the interface for scripts and other front ends. Don't read the
state files directly. With `--json`, a command prints one JSON object on
stdout and nothing else.

```sh
omdall status --json | jq -r '.plugins[] | "\(.name) \(.state)"'
omdall reviews demo --json | jq '.plugins[0].reviews[0].files'
omdall check --no-wait --json | jq -r '.results[] | "\(.name) \(.outcome)"'
```

`status` and `reviews` take `--json`, and so do the action commands `add`,
`adopt`, `check`, `update` and `doctor`. `approve` doesn't: approving stays
something you do yourself in a terminal.

Every object has `"schema": 1`. New fields may be added at any time. Removing
a field or changing what it means raises the schema number.

Text that comes from the plugin or the reviewer (subjects, authors, reasons,
file names, names from a manifest) has control characters escaped. Show it as
plain text, never as markup.

## Errors

When a command refuses, or when another run holds the lock and `--no-wait` was
given, nothing is done. stdout gets
`{"schema": 1, "error": "…", "code": "…"}`, stderr gets the message, and the
exit status is 1 (75 when busy). Use `code` to tell failures apart, not the
message:

| Code | Meaning |
|---|---|
| `busy` | another run holds the lock (`--no-wait`, exit 75) |
| `not_found` | no plugin by that name or id under the gate root |
| `not_installed` | `adopt`: the plugin has no installed copy |
| `already_guarded` | a clone under the gate root already maps to that id |
| `already_installed` | `add`: the id is installed outside the gate; use `adopt` |
| `refused_url` | the URL fails the transport policy, or there is none |
| `name_taken` | the clone directory already exists; pass `--dir` |
| `id_mismatch` | `adopt`: the repository is a different plugin |
| `config` | a setting is invalid |
| `error` | anything else |

## Action commands

`add`, `adopt`, `check`, `update` and `doctor` print their usual lines on
stderr, one line at a time as the work goes on, and the result object on
stdout when they finish:

```json
{
  "schema": 1,
  "command": "check",
  "ok": true,
  "results": [
    {"name": "omasync", "id": "acme.omasync", "outcome": "held", "sha": "…",
     "message": "REVIEW FAIL: …", "cleared": 0, "dirty": [], "review": null},
    {"name": "weather", "id": "acme.weather", "outcome": "approved", "sha": "…",
     "message": null, "cleared": 2, "dirty": [], "review": null}
  ],
  "summary": {
    "ready": ["weather"], "held": ["omasync"], "errors": [], "cleared": ["weather"]
  }
}
```

The object is printed even when the exit status is 1 because a plugin
failed, so you can see which one. `ok` is true when the exit status is 0.
`summary` is set for `check`, `add` and `adopt`, and `null` otherwise.

Each result has `name` (the clone directory), `id`, `outcome`, `sha` (the
commit concerned, or `null`), `message` (why, for anything but success),
`cleared` (structural findings the reviewer cleared), `dirty` and `review`.
The `outcome` values are a closed set:

| Command | `outcome` |
|---|---|
| `check` | `up_to_date`, `approved`, `approved_waiver` (an existing waiver let it through), `held`, `error` |
| `add` | `installed`, `installed_disabled` (`--no-enable`), `held`, `error` |
| `adopt` | `adopted`; `review` holds the outcome of the review that followed, as for `check` |
| `update` | `installed`, `up_to_date`, `blocked_dirty` (local changes, listed in `dirty`), `not_installed` (needs `update -p`), `rolled_back`, `error` |

`update` exits 0 even when a plugin failed, as it always has. Read the
outcomes. `add` and `adopt` exit 1 unless the review passed.

For `doctor`, `results` lists the problems found. Each has `name` (the
plugin, or `null` for a global check), `check`, `ok`, `message` and `fixed`. A
problem that `--fix` fixed has `ok` and `fixed` both true. `check` is one of
`root`, `opencode`, `omarchy`, `model`, `agent`, `clone`, `branch`, `origin`,
`installed_origin`, `installed_reviewed`, `installed_clean`, `hook_clone` and
`hook_installed`.

## status --json

Top level:

| Field | Meaning |
|---|---|
| `version`, `root`, `state` | the omdall version and its directories |
| `busy` | whether another run held the lock a moment ago, for display only; a script that must not wait should pass `--no-wait` |
| `features` | what this release supports: `activity`, `action-json`, `adopt`, `unguarded`, `attention`. Check for a feature before you use it. |
| `activity` | the contents of `activity.json` (see below), with `running` set to `null` unless a run holds the lock. `null` when there is no file yet. |
| `attention` | the plugins that need you, most urgent first: `{name, why}` |
| `unguarded` | installed plugins omdall does not manage (see below) |
| `plugins` | one entry per plugin under the gate root |

`attention` has one entry per plugin, with the most urgent reason only.
`why` is, from most urgent to least: `held` (a commit was held back),
`never_reviewed` (the installed commit has no review and no waiver), `ready`
(an approved commit is not installed), `dirty` (local changes would block
`update`). Nothing needs you when `attention` is empty and
`activity.running` is `null`. Unguarded plugins are not part of `attention`.

Each plugin:

| Field | Meaning |
|---|---|
| `name`, `id` | clone directory, manifest id (`null` if unreadable) |
| `clone`, `installed_dir`, `branch` | paths and default branch |
| `approved`, `installed`, `upstream` | full commit ids, or `null` |
| `upstream_url` | the clone's origin, without any user or password |
| `pending` | commits in `gate-approved..origin/<branch>` as of the last fetch, or `null` when unknown |
| `state` | `installed`, `ready to install`, `approved, not installed`, `held back` or `not reviewed yet` |
| `next` | `update`, `approve`, `check`, or `null` |
| `update_blocked` | why `update` would not move it: `no_approval`, `not_installed` (needs `update -p`), `dirty`, or `null` |
| `dirty` | changed files in the installed copy (these block `update`) |
| `never_reviewed` | the installed commit has no review and no waiver |
| `waiver` | `{date, user, reason}` if approved by hand |
| `cleared`, `cleared_file` | findings cleared for the approved commit |
| `held` | `{sha, reasons, subject, author}` for the held-back commit |
| `latest_review` | newest review, in the `reviews` format |

Each entry in `unguarded`:

| Field | Meaning |
|---|---|
| `id`, `name`, `dir` | manifest id and name, installed directory |
| `git`, `origin`, `head`, `dirty` | whether it is a git checkout, its origin without credentials, its commit, and whether it has local changes |
| `adoptable`, `reason` | whether `adopt <id>` can take it as it is, and if not why |

`reason` is one of `no_git` (not a git checkout), `no_origin`,
`local_origin` (origin is a path on this machine), `insecure_url` (the origin
fails the URL policy of `add`) and `name_taken` (the clone directory `adopt`
would use already exists, or no name can be derived from the URL). The first
three need `adopt --url`, `name_taken` needs `--dir`. `status` never fetches
to build this list.

## reviews --json

`reviews [<name>] --json` returns `plugins`. Each plugin has `name`, `id` and
`reviews`, newest first. Each review:

| Field | Meaning |
|---|---|
| `short`, `sha` | evidence directory name, full commit id |
| `subject`, `author` | from the commit |
| `date` | when the verdict was written |
| `verdict`, `passed`, `reasons` | the outcome |
| `hard` | structural failures, when the model was not asked |
| `findings`, `cleared` | counts |
| `approval` | `reviewed`, `waived` or `null` |
| `dir` | evidence directory |
| `files` | evidence files present: `patch`, `review_patch`, `mech`, `findings`, `hints`, `review`, `verdict`, `cleared` |

## activity.json

`<state>/activity.json` (by default `~/.local/state/omdall/activity.json`) is
rewritten whenever a run that takes the lock starts, moves to another phase or
ends. That includes the daily check, the tripwire and `approve` in a terminal.
Read-only commands never write it.

```json
{
  "schema": 1,
  "seq": 1842,
  "updated": "2026-11-03T03:00:41+01:00",
  "running": {
    "command": "check", "pid": 41233, "started": "2026-11-03T03:00:02+01:00",
    "plugin": "omasync", "phase": "reviewing", "index": 2, "total": 4,
    "phase_started": "2026-11-03T03:00:20+01:00", "timeout": 420
  },
  "last_run": {
    "command": "check", "started": "…", "finished": "…", "exit": 0,
    "summary": {"ready": ["weather"], "held": [], "errors": [], "cleared": []}
  },
  "last_check": {
    "finished": "…", "exit": 0,
    "summary": {"ready": ["weather"], "held": [], "errors": [], "cleared": []}
  }
}
```

- `seq` goes up on every write. A change of `seq` means "run `status --json`
  again".
- `running` is the run in progress, or `null`. `command` is the command name,
  or `tripwire` for the post-merge hook. `phase` is one of `fetching`,
  `checking` (structural checks), `reviewing` (the model call), `installing`,
  `validating`, `adopting` and `doctor`, or `null` before the run reports one
  (`approve` never does). `plugin`, `index` and `total` are `null` when they
  don't apply. `timeout` is set only while `reviewing`, so you can show the
  time spent against the limit.
- A run that crashed can leave `running` behind. The lock is the truth:
  `status --json` shows `activity.running` only while a run holds the lock.
- `last_run` is the last run to finish, whatever it was. `last_check` is the
  last `check`, `add` or `adopt` to finish, so it can drive a "last checked"
  line.

The file is display data. omdall never reads it to decide anything, and a
failure to write it never fails a run.

## Front ends

A graphical front end, such as the omdall shell plugin, needs only three
things:

1. Watch `activity.json`. When `seq` changes, or when the file appears, run
   `omdall status --json`.
2. Draw from that one object: `attention` and `activity.running` for the bar,
   `plugins` and `unguarded` for a panel, `features` to hide what an older
   omdall can't do.
3. Act with `omdall <command> --no-wait --json` (`check`, `update -p <name>`,
   `add <url>`, `adopt <id>`) and show the result object when it exits.
   Progress comes from `activity.json`, not from the command's output. Exit
   status 75 means another run is in progress; try again when `running` is
   `null`.

Approving and reading diffs belong in a terminal. Open
`omdall approve <name> --show` or `omdall reviews <name>` with
`omarchy-launch-floating-terminal-with-presentation`. `add` without a URL
asks for one there. The front end learns the outcome from `activity.json`, not
from the terminal's exit status.

With [`notify-action = "panel"`](configuration.md), a click on an omdall
notification opens the front end's panel instead of a terminal.

## Exit status

| Status | Meaning |
|---|---|
| `0` | done |
| `1` | failed, refused, or found problems |
| `75` | another run holds the lock; nothing was done (`--no-wait` only) |
| `130` | interrupted |

`--no-wait` works with `add`, `adopt`, `approve`, `check`, `update` and
`doctor`.
