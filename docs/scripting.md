# Scripting

`status --json` and `reviews --json` are the interface for scripts and other
front ends. Don't read the state files directly. Each command prints one JSON
object on stdout and nothing else.

```sh
omdall status --json | jq -r '.plugins[] | "\(.name) \(.state)"'
omdall reviews demo --json | jq '.plugins[0].reviews[0].files'
```

Every object has `"schema": 1`. New fields may be added at any time. Removing
a field or changing what it means raises the schema number. On failure, stdout
gets `{"schema": 1, "error": "…", "code": "…"}`, stderr gets the message, and
the exit status is 1.

Text that comes from the plugin or the reviewer (subjects, authors, reasons,
file names) has control characters escaped.

## status --json

Top level: `version`, `root`, `state`, `busy`, `plugins`. `busy` tells you
whether another run held the lock a moment ago. It is only for display. A
script that must not wait should pass `--no-wait`.

Each plugin:

| Field | Meaning |
|---|---|
| `name`, `id` | clone directory, manifest id (`null` if unreadable) |
| `clone`, `installed_dir`, `branch` | paths and default branch |
| `approved`, `installed`, `upstream` | full commit ids, or `null` |
| `state` | `installed`, `ready to install`, `approved, not installed`, `held back` or `not reviewed yet` |
| `next` | `update`, `approve`, `check`, or `null` |
| `dirty` | changed files in the installed copy (these block `update`) |
| `never_reviewed` | the installed commit has no review and no waiver |
| `waiver` | `{date, user, reason}` if approved by hand |
| `cleared`, `cleared_file` | findings cleared for the approved commit |
| `held` | `{sha, reasons}` for the held-back commit |
| `latest_review` | newest review, in the `reviews` format |

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

## Exit status

| Status | Meaning |
|---|---|
| `0` | done |
| `1` | failed, refused, or found problems |
| `75` | another run holds the lock; nothing was done (`--no-wait` only) |
| `130` | interrupted |

`--no-wait` works with `add`, `approve`, `check`, `update` and `doctor`.
