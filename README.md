# omarchy-plugin-gate

Review-before-update gate for [Omarchy](https://omarchy.org) shell plugins.

Omarchy plugins are unsandboxed code inside the long-lived `omarchy-shell`
process. `omarchy plugin update` fast-forwards them from GitHub, which means an
upstream commit is a code change to a process that already holds your session.
This gate puts a review step in front of that: upstream changes are fetched and
reviewed in a clone you own, and the installed plugin can only move to a commit
that passed.

## Requirements

- Omarchy with the `omarchy` command on `PATH` (every candidate is validated
  with `omarchy plugin validate`)
- `python3` 3.14 or newer (Omarchy's system Python) and `git`; the gate uses the
  standard library only, so there is nothing to `pip install`
- [OpenCode](https://opencode.ai) on `PATH` (the reviewer runs headlessly)

## Install

```sh
git clone https://github.com/haplo/omarchy-plugin-gate ~/Work/omarchy-plugin-gate
cd ~/Work/omarchy-plugin-gate
mise trust          # once: allow mise to run this project's tasks
mise run install
```

The installation does several things:

1. Symlinks the `omarchy-plugin-gate` command to `~/.local/bin`.
2. Links the shell completions into `~/.local/share`.
3. Places the reviewer agent prompt into `~/.config/opencode/agents/`.
4. Copies [`config.example.toml`](config.example.toml) to
`~/.config/omarchy-plugin-gate/config.toml` if there is no config file yet.
5. Installs the systemd user units and enables the daily check. Use `mise run
   install:no-timer` to skip the timer.

Without mise, [scripts/install.sh](scripts/install.sh) does the same thing.

### Shell completions

`install.sh` links completions for bash, zsh and fish into
`$XDG_DATA_HOME` (`~/.local/share` when it is unset or not absolute):

| Shell | Path |
|---|---|
| bash | `$XDG_DATA_HOME/bash-completion/completions/omarchy-plugin-gate` |
| fish | `$XDG_DATA_HOME/fish/vendor_completions.d/omarchy-plugin-gate.fish` |
| zsh | `$XDG_DATA_HOME/zsh/site-functions/_omarchy-plugin-gate` |

bash finds its file through bash-completion, and fish scans
`vendor_completions.d` itself. zsh has no per-user directory that it scans, so
add this to `~/.zshrc`, before `compinit`:

```sh
fpath=(~/.local/share/zsh/site-functions $fpath)
```

They complete the commands, their options, the plugin names under the gate
root, and the held commit for `approve --sha`. The root and state come from
`--root` and `--state` on the line, the environment and the config file, as
they do for the command. Both `--option value` and `--option=value` work.

Then wire up whatever is already cloned:

```sh
omarchy-plugin-gate doctor --fix
```

## Quick start

```sh
# install a new plugin end to end: clone, review, install disabled, enable on PASS
omarchy-plugin-gate add https://github.com/ninepointlabs/omasync

# review upstream changes (the daily timer runs this)
omarchy-plugin-gate check

# after reading a failed review yourself, accept that one commit
omarchy-plugin-gate approve <name>

# apply approved commits to the installed copies
omarchy-plugin-gate update

# what is installed, approved, upstream, held
omarchy-plugin-gate status

# every recorded review, newest first, with its evidence
omarchy-plugin-gate reviews <name>
```

A notification appears only when something needs a decision: an update is ready
to install, or a review was held back. A successful `update` closes it.

`add` clones only over `https://`, `ssh://` (or `user@host:path`), `file://`,
or from an absolute local path. It refuses `http://` and `git://`, which are not
authenticated, so anyone on the network path could choose the code that gets
reviewed and installed; it also refuses transport helpers (`ext::…`) and
anything that looks like an option. When `omarchy-git-url-check` is installed,
the URL must pass it too, and the clone itself runs with git limited to those
protocols whatever your git config allows. `doctor` reports a clone whose
origin uses `http://` or `git://`.

## How it works

```
~/Work/omarchy-plugins/<name>/     normal clone, origin = upstream
  main                             your checkout, safe to branch and push from
  refs/heads/gate-approved         exactly what passed review or was waived

~/.config/omarchy/plugins/<id>/    installed copy, origin = the clone above
```

Because the installed copy fetches from the clone, plain `omarchy plugin update`
can only ever pull `main` from that clone — which is either approved or your own
work. `check` fetches upstream, diffs `gate-approved..origin/<branch>`, reviews
it, and advances `gate-approved` only on `REVIEW PASS` or a recorded one-time
waiver. `update` then fast-forwards the installed copy to that ref, validates
the manifest, and asks the shell to rescan.

A fast-forward keeps edited and untracked files, and nobody reviewed those, so
`update` refuses an installed copy with modified, staged or untracked files and
names them; commit, remove or `git checkout` them first. Files your git ignore
rules match (a plugin's cache, say) do not stop an update. `status` shows
local changes as `modified` and says when the installed commit was never
reviewed (an adopted plugin, or a commit made in the installed copy); `doctor`
reports both as problems and lists ignored files for information.

Every candidate keeps its evidence under
`~/.local/state/omarchy-plugin-gate/<name>/`:

```
reviews/<short-sha>/patch        the exact diff that was reviewed
reviews/<short-sha>/patch.review the copy handed to the reviewer (patch + code word)
reviews/<short-sha>/mech.txt     hard structural check results
reviews/<short-sha>/findings.txt structural findings handed to the reviewer
reviews/<short-sha>/hints.txt    keywords handed to the reviewer
reviews/<short-sha>/review.txt   the reviewer's full output
reviews/<short-sha>/verdict      REVIEW PASS/FAIL plus reasons
reviews/<short-sha>/cleared      findings the reviewer cleared, and why
reviewed/<sha>                   approvals that came from a REVIEW PASS
waived/<sha>                     one-time human approvals (verdict kept)
held                             the last commit that failed and why
```

Runs that write (`add`, `approve`, `check`, `update`, `doctor --fix` and the
tripwire) take a lock, `gate.lock` in the state directory, so the nightly check,
a command you run and a hook never write the same evidence at once. A second
run prints `waiting for another run to finish…` and waits; with `--no-wait` it
exits 75 instead, having done nothing. `status`, `reviews`, `doctor` and
`approve --dry-run` never wait. `gate-approved` only moves from the commit
the run read, so it cannot jump over a change made elsewhere. The gate's own
merges of approved commits do not start the tripwire.

## Scripting and other front ends

`status --json` and `reviews --json` are the interface for scripts and
graphical front ends; the state files are not. Each prints one JSON object on
stdout and nothing else. Every object carries `"schema": 1`; fields are only
ever added, and a removal or a change of meaning bumps the number. A failure
prints `{"schema": 1, "error": "…", "code": "…"}` on stdout, the message on
stderr, and exits 1.

```sh
omarchy-plugin-gate status --json | jq -r '.plugins[] | "\(.name) \(.state)"'
omarchy-plugin-gate reviews demo --json | jq '.plugins[0].reviews[0].files'
```

`status --json` has `version`, `root`, `state`, `busy` and `plugins`. Each
plugin has:

| Field | Meaning |
|---|---|
| `name`, `id` | clone directory under the root, manifest id (`null` when unreadable) |
| `clone`, `installed_dir`, `branch` | paths and the default branch |
| `approved`, `installed`, `upstream` | full commit ids, or `null` |
| `state` | `installed`, `ready to install`, `approved, not installed`, `held back` or `not reviewed yet`, as in `status` |
| `next` | the command that moves it on: `update`, `approve`, `check`, or `null` |
| `dirty` | files changed in the installed copy, which stop `update` |
| `never_reviewed` | the installed commit has neither a review nor a waiver |
| `waiver` | `{date, user, reason}` when the approved commit was waived by hand |
| `cleared`, `cleared_file` | findings the reviewer cleared for the approved commit |
| `held` | `{sha, reasons}` for the commit held back |
| `latest_review` | the newest review, in the form `reviews` gives |

`reviews [<name>] --json` lists `plugins`, each with `name`, `id` and
`reviews`, newest first. A review has `short` (its directory name), `sha`,
`subject`, `author`, `date` (when the verdict was written), `verdict`,
`passed`, `reasons`, `hard` (structural failures, when the model was never
asked), `findings` and `cleared` counts, `approval` (`reviewed`, `waived` or
`null`), `dir`, and `files`: the evidence files that exist, by name (`patch`,
`review_patch`, `mech`, `findings`, `hints`, `review`, `verdict`, `cleared`).

Text that came from the plugin or the reviewer (subjects, authors, reasons,
file names) has its control characters escaped, as on the terminal. `busy` says
whether another run held the lock a moment ago, for display; it can be stale by
the time you read it, so a script that must not wait passes `--no-wait` to the
command itself.

| Exit status | Meaning |
|---|---|
| `0` | done |
| `1` | failed, refused, or found problems (`check` with errors, `doctor` with problems) |
| `75` | another run holds the lock; nothing was done (`--no-wait` only) |
| `130` | interrupted |

`--no-wait` works on `add`, `approve`, `check`, `update` and `doctor`. The
nightly check and the tripwire always wait, so neither skips a review because
something else was running.

## Two layers of review

**Structural checks** run first, with no model involved, in two tiers.

*Hard failures* are an immediate `REVIEW FAIL`; the reviewer is never called:

- diffs larger than `--max-patch` (default 2 MiB, sized for a
  reviewer model with a 1M-token context), which the reviewer could not read in
  full
- diffs that are not valid UTF-8, which OpenCode would not hand to the reviewer
  as text; the offending files are named
- files git treats as binary (a single NUL byte is enough) that the reviewer
  would see only as "Binary files differ" although they are code: a code
  suffix (`.qml`, `.js`, `.sh`, `.py`, `.json`, `.desktop`, …) or a `qmldir`,
  an entry point, or an executable
- native code: an ELF file under any name, or a `.so`, `.node`, `.dll` or
  `.dylib`
- a `.gitattributes` anywhere in the candidate tree that sets a `filter` (Git
  LFS sets `filter=lfs`), a `.lfsconfig`, or a changed file that is an LFS
  pointer. The patch shows the committed blob, but a checkout runs whatever
  filter is configured on your machine (`git lfs install` sets one up
  globally), so the files on disk would not be the ones reviewed. The gate's
  own merges and resets ignore the plugin's attributes as well
- symlinks, submodules and `.gitmodules`: the patch shows a symlink only as
  its target path and a submodule only as `Subproject commit <sha>`, so the
  reviewer never sees what they point at
- a file added or changed under `.git/` or `.ssh/`, or named `authorized_keys`
  or `sudoers`, which no plugin has a use for; and an executable file in any
  protected path (the findings list below), such as `systemd/run` or
  `tool.desktop`
- a manifest `id` change, or a manifest that can no longer be read
- a manifest `id` that is not a valid plugin id: letters, digits, `.`, `_` and
  `-`, starting with a letter or digit, no `..`, and not in the reserved
  `omarchy.*` namespace. The gate checks this itself, since the id names the
  installed copy's directory
- `manifest.json` that does not validate at the candidate commit
  (`omarchy plugin validate`). Without `omarchy` on `PATH` nothing can be
  validated, so every candidate fails; `doctor` reports a missing `omarchy`
- entry points that escape the plugin directory or name a file missing from the
  candidate commit
- more than 40 structural findings in one candidate

*Findings* are pattern matches that usually, but not always, mean trouble. They
are numbered `F1`, `F2`, …, printed one per line before the review starts, and
handed to the reviewer with the patch:

- binary files outside common asset types (PNG, JPEG, GIF, WebP, ICO, AVIF,
  BMP, WOFF, WOFF2, TTF)
- asset files whose contents do not start the way their type does, such as a
  `.png` that is not a PNG image
- protected paths some plugins do use: `systemd/` (a directory of QML that shows
  unit status, say), `omarchy/hooks`, `*.service`, `*.timer`, `*.socket`,
  `*.path`, `*.desktop`, `*.pem` (a CA bundle), `*.key`, `*.p12`; and deleting
  any protected file, including the hard-failure paths above
- newly executable files without a shebang
- manifest `kinds` or `entryPoints` changes
- added code lines that pipe a download or decoder into a shell, use `/dev/tcp`,
  or pipe into `sudo`/`pkexec`

The reviewer must answer every finding, on its own line after the verdict:

```
REVIEW PASS
F1 CLEARED systemd/ holds QML that displays unit status; nothing is installed
F2 CLEARED icon.bin is loaded by Icon.qml as image data
```

A `REVIEW PASS` with a finding left unanswered, answered twice, answered
`CONFIRMED`, cleared without a reason, or with an answer to a finding that does
not exist is recorded as `REVIEW FAIL`. A pass that cleared findings writes
`reviews/<short-sha>/cleared`, and `check`, `status` and the notification all
say so, so you know which approvals are worth a second look.

**The reviewer** is a read-only OpenCode agent (`plugin-reviewer`) with no shell,
no write access and no network tools. It runs from the candidate's review
directory and may only read, glob and grep inside it, so it sees the patch and
nothing else. It receives the patch, the structural findings and keyword hints,
and must answer on the first line with exactly `REVIEW PASS` or `REVIEW FAIL`,
followed by its finding answers and one reason per line. It never runs from the
plugin checkout, so a hostile `.opencode/` configuration in the diff cannot
execute. Reviewer crash, timeout, or a missing verdict line all fail closed.

The prompt also lists the commit subjects, authors and changed files. The
plugin's author wrote those, so they sit in a block marked as untrusted data,
with control characters escaped and each line cut to 200 characters.

The copy of the patch the reviewer gets (`patch.review`) ends with a line
carrying a random code word, generated for each run and never put in the prompt.
The reviewer must finish its answer with `SEEN <word>`. Without the right word
the verdict is `REVIEW FAIL`: the reviewer did not receive, or did not finish,
the whole patch, so whatever it said was not about all of the code. If the
attachment arrives cut off, the reviewer can page through `./patch.review` with
its read tool.

## Approving a failed review

`approve` is the deliberate escape hatch. It never guesses: without `--sha` it
takes the commit named in `held`, prints the verdict, structural findings, and
patch path, then asks for a reason. The reason may be empty; `--reason TEXT`
skips the prompt, which is also required when stdin is not a terminal. With
`--show` it prints the patch before asking, and `-n` / `--dry-run` shows the
decision without changing anything.

The patch `--show` prints is computed fresh, from where `gate-approved` is now
to the candidate: exactly what the approval lets through. When that is not the
patch the recorded review saw (`gate-approved` moved since, or the commit was
never reviewed), `approve` warns that the recorded review covered a different
diff. A commit with no review verdict at all needs `--show` or `--reason`.

Everything printed from the plugin or the reviewer has its control characters
escaped: the patch under `--show`, and the verdict, findings and held reasons
in `approve`, `status` and `add`. An escape sequence in a hostile patch shows
up as `\x1b…` instead of erasing lines or writing to your clipboard. The
reviewer's answer is cleaned the same way before it is stored in `verdict`,
`cleared` and `held`; `review.txt` keeps its raw output.

```sh
omarchy-plugin-gate approve my-plugin          # prompt for a reason
omarchy-plugin-gate approve my-plugin --show   # read the diff first
omarchy-plugin-gate approve my-plugin --reason "upstream fix I checked"
omarchy-plugin-gate update -p my-plugin
```

A waiver is one commit, not a standing trust setting. It lives in
`waived/<sha>` with the date, user, reason, base commit, and the blob hash of
the patch it let through (`patch-blob`); when the recorded review saw a
different patch, its hash is kept too (`evidence-blob`). The failed verdict is left untouched, so `status`
shows both `REVIEW FAIL` and `approval waived by hand`. `approve` moves
`gate-approved` and installs the hooks; `update` still does the installation.

The same works for a plugin whose first review failed in `add`: the clone is
kept and the commit is held, so `approve <name>` followed by
`update -p <name>` installs and enables it.

Approval covers the held candidate only. It does not fetch, and `--sha` must
name a commit that is still reachable from `origin/<branch>`. Hard structural
failures can be waived too: the failures and findings are printed first, so read
them before you answer.

## Tripwire

`doctor --fix` installs a `post-merge` hook in both the clone and the installed
copy. If a merge did not come through the gate (a manual `git pull`, say), the
hook reviews the incoming commits and, on failure, resets them and disables the
plugin. Commits you authored yourself are never reviewed or rolled back.

The rollback (`git reset --keep`) keeps uncommitted changes in files the merge
did not touch. When going back would overwrite one of your changes, the hook
leaves the merged commit in place rather than discard your work: it disables
the plugin (in the installed copy), logs `could not roll back`, and notifies
you, so you can sort it out by hand. `update` rolls back the installed copy the
same way when a merge goes wrong.

Each hook names its plugin, and the installed copy is recognised by the id in
the approved commit, so a merge cannot hide from the hook by changing the
manifest id. Hooks written by earlier releases did not name their plugin;
`check`, `approve` and `update` rewrite them, and `doctor --fix` does too.
Until then, such a hook only logs an error to `hooks.log`.

The gate writes hooks only into the repository's own git directory and only
over a hook it wrote itself. When `core.hooksPath` points elsewhere (a global
hooks directory, say), a hook there would run in every repository using it, so
no tripwire is installed; and a `post-merge` hook of your own is never
replaced. `check`, `approve` and `update` warn about either case and `doctor`
reports it as a problem. Unset `core.hooksPath` for the repository, or move
your hook aside, then run `doctor --fix`.

This is a net, not the main gate: `omarchy-shell` may already have rescanned by
the time a hook finishes. The gate is what prevents bad code from arriving.

## Settings

Every setting can be given as an option, an environment variable, or a key in
the config file. Options win over the environment, which wins over the config
file. Options go before or after the command; an option given on both sides of
the command takes the value after it. An empty variable or config value counts
as unset.

```sh
omarchy-plugin-gate --model venice/claude-opus-4-7 check
omarchy-plugin-gate check -p omasync --timeout 900
```

The config file is `$XDG_CONFIG_HOME/omarchy-plugin-gate/config.toml`
(`~/.config/omarchy-plugin-gate/config.toml` when `XDG_CONFIG_HOME` is unset or
not an absolute path), in TOML:

```toml
model = "venice/claude-opus-4-7"
timeout = 900
```

A missing file is fine. Unknown keys, wrong types and invalid TOML are errors.
`timeout` and `max-patch` are TOML integers, everything else is a string, and
`root` and `state` must be absolute paths or start with `~/`. Install copies
[`config.example.toml`](config.example.toml) there, with every setting commented
out at its default, and never overwrites an existing file. The nightly check
reads the same file.

| Option | Variable | Config key | Default | Purpose |
|---|---|---|---|---|
| `--root DIR` | `OMARCHY_PLUGIN_GATE_ROOT` | `root` | `~/Work/omarchy-plugins` | where working clones live |
| `--state DIR` | `OMARCHY_PLUGIN_GATE_STATE` | `state` | `~/.local/state/omarchy-plugin-gate` | evidence and markers |
| `--agent NAME` | `OMARCHY_PLUGIN_GATE_AGENT` | `agent` | `plugin-reviewer` | OpenCode agent that reviews, read from `~/.config/opencode/agents/<name>.md` |
| `--model ID` | `OMARCHY_PLUGIN_GATE_MODEL` | `model` | OpenCode's default | model for the reviewer, e.g. `venice/claude-opus-4-7` |
| `--notify POLICY` | `OMARCHY_PLUGIN_GATE_NOTIFY` | `notify` | `all` | `all`, `ready`, or `none` |
| `--timeout SECONDS` | `OMARCHY_PLUGIN_GATE_TIMEOUT` | `timeout` | `420` | reviewer timeout, seconds |
| `--max-patch BYTES` | `OMARCHY_PLUGIN_GATE_MAX_PATCH` | `max-patch` | `2097152` | largest diff that is auto-reviewed; assumes a 1M-token model, so lower it for smaller ones (about 3 bytes per token, minus headroom) |

Tripwire hooks record the root and state of the run that installed them, so a
merge reviewed by the hook uses the same clones and evidence directory whatever
the environment of the `git pull`. `check`, `approve` and `update` rewrite
hooks that record a different root, state or plugin; `doctor` reports them and
`doctor --fix` rewrites them.

Re-run `mise run install` after pulling a change to the reviewer agent;
`doctor` reports an installed agent that no longer matches the repository.

## Already-installed plugins

`add` refuses an id that is already installed. To adopt one that Omarchy
installed from GitHub:

```sh
git clone <upstream-url> ~/Work/omarchy-plugins/<name>
git -C ~/.config/omarchy/plugins/<id> remote set-url origin ~/Work/omarchy-plugins/<name>
omarchy-plugin-gate check        # reviews the current tree, sets gate-approved
omarchy-plugin-gate doctor --fix # tripwires
```

`check` bootstraps the first review from the whole tree when no
`gate-approved` exists yet. That review covers upstream's current commit; if
the installed copy is at another one, `status` and `doctor` report it as never
reviewed until `update` moves it.

## Development

The gate is Python in `src/omarchy_plugin_gate/`, started by the launcher
`bin/omarchy-plugin-gate`. Development tools come from mise and uv:

```sh
mise install      # uv
mise run sync     # pytest, ruff and ty, pinned in uv.lock, into .venv
mise run lint     # ruff format --check, ruff check, ty check, bash -n
mise run fmt      # ruff format and safe fixes
mise run test     # unit tests and the fixture suite
```

## Tests

```sh
mise run test     # both suites
mise run test:unit
mise run test:fixture   # or: tests/run [--keep] [suite ...]
```

The unit tests (pytest) cover the pure pieces in isolation: path, danger and
hint patterns; NUL-separated git parsing with awkward file names; every way a
reviewer answer can fail to clear a finding or prove it saw the patch; the
state file formats; the `status` and `reviews` records and their JSON; the
lock's exit status 75 with `--no-wait`; the shell completion scripts staying
in step with the parser; and the fail-closed paths (a git error mid-review, a reviewer that
crashes after `REVIEW PASS`, a reviewer that times out and leaves children
behind).

The fixture suite (`tests/run`, bash, needs `jq`) is the end-to-end contract.
Each suite in `tests/suites/` runs against its own throwaway repositories in a
temporary directory, with a stub reviewer and stub `omarchy` commands from
`tests/stubs/`; name suites to run only those (`tests/run approve hooks`). It
covers the bootstrap review, clean and
partial updates, every hard structural failure (asserting the model is *not*
called), every kind of structural finding reaching the reviewer, each way a
reviewer can fail to clear a finding, a missing, wrong or planted code word,
reviewer failure and crash, the reviewer's working directory, options winning
over the environment and the environment over the config file, install copying
the example config without overwriting one, shell completions being linked on
install and removed on uninstall (keeping a file of your own) and completing
plugin names and held commits in bash and, when installed, fish, `doctor`
spotting a stale reviewer agent, update applying and refusing (including an
installed copy with local changes or an unreviewed commit), the tripwire
rolling back a rejected pull while leaving local commits alone, notification
policy, one-time approvals (including dry run, `--sha`, `--show`, and the
resulting update), both `add` outcomes, `add` refusing unsafe URLs before
cloning, installing a plugin whose `add`
review failed once it has been approved by hand, the JSON that `status` and
`reviews` print (failures included), and `--no-wait` exiting 75 without
reviewing or moving anything. No network, no real plugin install.

## Uninstall

```sh
mise run uninstall
```

Removes the command, reviewer agent, completions, units and the tripwires. The
config file, working clones, review evidence and installed plugins are kept;
the output explains how to point the installed copies back at their upstream
repositories.

## Limits, honestly

- The reviewer is advisory. The hard structural checks and the retained patch
  and transcript for every approved commit are the durable record. Findings the
  reviewer cleared are a judgement call a hostile diff may try to argue it
  into; `cleared` lists them, so check those approvals first. Read a diff
  yourself when the gate says `REVIEW FAIL` — use `approve --show` or the patch
  path in `status`.
- `origin/main` in a working clone is whatever upstream last published; the gate
  only governs what the installed plugin sees. Anyone with write access to this
  machine can move `gate-approved` by hand.
- Plugins still run unsandboxed. This gate makes updates reviewable; it does not
  sandbox the plugin.

## License

[MIT](LICENSE).
