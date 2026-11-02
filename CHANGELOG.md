# Changelog

All notable changes to omarchy-plugin-gate. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## Unreleased

### Security

- Files changed in the installed copy were never noticed. `update` and
  `status` compared only the installed commit, so an edited or untracked file
  in `~/.config/omarchy/plugins/<id>` survived every fast-forward without
  review, and a plugin adopted at a commit the gate never reviewed looked
  installed and approved. `update` now refuses an installed copy with
  modified, staged or untracked files and names them; files matched by
  ignore rules do not stop it. `status` shows local changes as `modified` and
  says `installed commit never reviewed` when the installed commit has neither
  a review nor a waiver; `doctor` reports both as problems and lists ignored
  files for information.
- Installing the tripwire could replace hooks that were not the gate's. With
  `core.hooksPath` set, git's hooks directory is wherever that points, often
  one shared by every repository, so the gate replaced the shared `post-merge`
  hook and its tripwire ran after merges everywhere. An existing `post-merge`
  hook in the repository was also replaced without a backup. The gate now
  writes a hook only inside the repository's git directory and only over one
  it wrote itself; otherwise `check`, `approve` and `update` warn, and `doctor`
  reports the reason as a problem. `doctor --fix` now also counts a hook it
  could not install as a problem.
- A rollback could delete uncommitted work. The tripwire, and `update` when a
  merge went wrong, rolled back with `git reset --hard`, which also threw away
  uncommitted changes the merge had left alone. They now use `git reset
  --keep`, which keeps them. When even that would overwrite a local change,
  nothing is discarded: the merged commit stays, the plugin is disabled (when
  it is the installed copy), and the gate logs `could not roll back … without
  discarding local changes` and sends a `rollback failed` notification.
- Concurrent runs could mix up the audit trail. The nightly check, a command
  run by hand and a tripwire hook could run at once, so one run's re-review
  deleted evidence another was writing, the `held` file raced, and
  `gate-approved` was moved without checking where it pointed. `add`,
  `approve`, `check`, `update`, `doctor --fix` and the tripwire now take a lock
  (`gate.lock` in the state directory); a second run prints `waiting for
  another run to finish…` and waits. `status`, `doctor` and `approve
  --dry-run` do not. `gate-approved` moves only if it still points where the
  run read it (or, for `add`, only if it does not exist yet). The gate's own
  merges of approved commits no longer start the tripwire, which would have
  waited for the lock the gate holds.
- `add` cloned whatever URL it was given. Over `http://` or `git://`, which
  are not authenticated, anyone on the network path could choose the plugin
  that was reviewed and installed, and a transport helper (`ext::`) runs a
  command if the user's git config allows it. `add` now accepts only
  `https://`, `ssh://`, `user@host:path`, `file://` and absolute paths, refuses
  `::` helpers and anything starting with `-`, also requires
  `omarchy-git-url-check` to pass when it is installed (as `omarchy plugin add`
  does), and clones with `GIT_ALLOW_PROTOCOL=https:ssh:file`, so a
  `url.insteadOf` rewrite or a permissive `protocol.allow` cannot widen that.
  `doctor` reports a clone whose origin uses `http://` or `git://`.
- `approve` showed the stored evidence, not the diff it approved. It printed
  and hashed the patch the recorded review saw, but moved `gate-approved` from
  wherever it was now, which may be a different base; and `--sha` on a commit
  that was never reviewed went ahead with only a warning. `approve` now
  computes the diff from the current `gate-approved` to the candidate, prints
  that under `--show`, records its hash as `patch-blob`, and warns when the
  recorded review covered a different diff; the reviewed patch's hash is then
  kept as a new `evidence-blob` line in the waiver. A commit with no review
  verdict needs `--show` or `--reason`.

## [0.5.0] - 2026-10-31

### Security

- A hostile patch or reviewer answer could send escape sequences to the
  terminal. `approve --show` wrote the patch bytes as they were, so a plugin
  could erase or hide lines of the diff being waived, or set the clipboard
  through OSC 52. The reviewer's output was stripped of colour codes only, so
  other sequences, carriage returns and bidi controls reached `verdict`,
  `cleared` and `held`, and from there `status`, `approve` and `add`. `--show`
  now prints the patch with control characters escaped (`\x1b…`), keeping
  newlines and tabs; the verdict, findings and held reasons are escaped
  wherever they are printed; and the reviewer's answer is cleaned of every
  escape sequence and control character before anything is stored.
  `review.txt` still holds the raw output.
- Code could be hidden from the reviewer as a binary file. git treats a file
  with one NUL byte in its first 8000 bytes as binary, so a `.js` or `.qml`
  carrying one reached the reviewer as "Binary files differ" and only a
  clearable finding; and a file with an asset suffix was never flagged at all,
  so a native library named `icon.png` passed silently. Now a binary file is a
  hard failure when it has a code suffix (`.qml`, `.js`, `.sh`, `.py`,
  `.json`, `.desktop` and the like) or is a `qmldir`, is an entry point, is
  executable, is ELF under any name, or is a `.so`, `.node`, `.dll` or
  `.dylib`. An image or font whose contents do not start the way its type
  does is a new finding, `asset file does not look like its type`. Other
  binaries stay a finding, and a deleted binary is no longer reported. The
  `plugin-reviewer` agent mentions the new finding; re-run `mise run install`.
- Git LFS and other filter drivers could put unreviewed content on disk. The
  reviewer sees the committed blob, which for an LFS-tracked file is a
  three-line pointer, but every checkout (`omarchy plugin add` and `update`,
  and the gate's own merges and resets) reads the plugin's `.gitattributes`
  and, with `git lfs install` or any other filter configured on the machine,
  writes whatever the filter returns. A `.gitattributes` anywhere in the
  candidate tree that sets a `filter`, a `.lfsconfig`, or a changed file that
  is an LFS pointer is now a hard failure. The gate's own merges and resets
  also ignore the plugin's attributes, so not even a waived commit runs a
  filter there.
- The tripwire skipped a pull into the installed copy that changed the
  manifest id. It worked out which plugin a directory belonged to from the
  `manifest.json` left by the merge, so a commit with a new id was never
  reviewed or rolled back. Hooks now name their plugin, and the installed copy
  is recognised, and disabled on a rollback, by the id in the approved commit.
  `update` also takes the id from the approved commit when it rolls back.
  Hooks written by earlier releases are rewritten by the next `check`,
  `approve`, `update` or `doctor --fix`; until then they only log an error.
- Commit metadata reached the reviewer as part of its instructions. The
  headline commit, the commit list (abbreviated hash, author, subject) and the
  changed-file list went into the prompt as they were, so a subject or author
  name could carry escape sequences, bidi controls, carriage returns or long
  instructions. They now sit in a block marked as written by the plugin
  author and untrusted, with control characters escaped, the block's `<<<` and
  `>>>` markers broken up, and each line cut to 200 characters. The plugin
  name and id are escaped and bounded the same way.
- Validation was skipped when `omarchy` was not on `PATH`, and the gate never
  checked the manifest id itself. `omarchy plugin validate` was the only check
  that refused symlinks and bad ids, so without it a candidate passed with
  neither checked. A missing `omarchy` now fails the candidate, and `doctor`
  reports it. The gate also refuses a manifest id that is not a valid plugin
  id (letters, digits, `.`, `_` and `-`, starting with a letter or digit, no
  `..`, not `omarchy.*`), the same rule `omarchy plugin validate` applies, and
  never builds a path from such an id: before, an id such as `/etc` made the
  installed copy's directory `/etc`.
- Symlinks and submodules were not checked by the gate. The patch shows a
  symlink only as its target path and a submodule only as `Subproject commit
  <sha>`, so the reviewer never saw what they pointed at; symlinks were refused
  only when `omarchy plugin validate` ran, and submodules not at all. An added
  or changed symlink, a submodule, or a `.gitmodules` file is now a hard
  failure.

## [0.4.0] - 2026-10-29

### Added

- Shell completions for bash, zsh and fish: the commands, their options, the
  settings options, the plugin names under the gate root, and the held commit
  for `approve --sha`. The plugin names come from a hidden `_complete` command,
  so `--root` and `--state` on the line, the environment and the config file
  apply exactly as they do for the command. `--option=value` completes like
  `--option value`. `install.sh` links the scripts into `$XDG_DATA_HOME`
  (`bash-completion/completions`, `fish/vendor_completions.d` and
  `zsh/site-functions`); `uninstall.sh` removes those links, but only when they
  point into the repository. bash finds its file through bash-completion and
  fish scans its own directory; zsh needs
  `fpath=(~/.local/share/zsh/site-functions $fpath)` before `compinit`.

### Changed

- `--fix` is now only accepted by `doctor`. The other subcommands accepted it
  and silently ignored it.
- `check` and `add` print the structural findings, one per line, before the
  reviewer starts. The tripwire hook writes them to `hooks.log`.
- `update -p <name>` installs and enables a plugin that is approved but has no
  installed copy yet, the way `add` would have. Plain `update` lists such
  plugins instead, so one removed on purpose stays removed, and `status` names
  the command.

### Fixed

- A plugin whose first review failed in `add` could not be installed: `add`
  refused the existing clone and `update` skipped it. `add` now records the
  failed commit as held, so `approve <name>` finds it, and points to
  `approve` and `update -p <name>`. The same path recovers a failed
  `omarchy plugin add`.

## [0.3.0] - 2026-10-29

### Added

- Every setting is also an option: `--root`, `--state`, `--agent`, `--model`,
  `--notify`, `--timeout` and `--max-patch`. They go before or after the
  command, win over the matching `OMARCHY_PLUGIN_GATE_*` variable, and take
  the value after the command when given on both sides. An empty value is an
  error. `OMARCHY_PLUGIN_GATE_AGENT` is now documented.
- A TOML config file, `$XDG_CONFIG_HOME/omarchy-plugin-gate/config.toml`
  (`~/.config/omarchy-plugin-gate/config.toml` by default), with the lowest
  priority: options win over variables, which win over the file. Its keys are
  the option names (`root`, `state`, `agent`, `model`, `notify`, `timeout`,
  `max-patch`). Unknown keys, wrong types and invalid TOML are errors; `root`
  and `state` may start with `~/`. The repository ships `config.example.toml`
  with every setting commented out at its default, and `install.sh` copies it
  into place when there is no config file yet; it never overwrites one, and
  `uninstall.sh` keeps it. Both scripts take the root and state from the config
  file as well. `doctor` reports whether the file exists.

### Changed

- Rewritten in Python. The gate runs on the system `python3` (3.14 or newer,
  Omarchy's) with the standard library only; `bin/omarchy-plugin-gate` is now a
  launcher that runs the code in `src/omarchy_plugin_gate/` with `python3 -I`,
  so `PYTHONPATH`, user site-packages and the working directory cannot inject
  code. Commands, exit codes, messages, the state layout and its file formats
  are unchanged; existing clones, evidence and waivers keep working.
- Requirements are now `python3` and `git`. `jq` is no longer needed at
  runtime (the fixture suite still uses it). `install.sh` checks the Python
  version.
- Development tooling: pytest unit tests alongside the fixture suite, `ruff`
  for formatting and linting, `ty` for type checking, all locked in `uv.lock`.
  `mise.toml` pins `uv` and adds `sync`, `test:unit`, `test:fixture` and `fmt`
  tasks; `lint` now runs `ruff` and `ty` as well as `bash -n`, and `test` runs
  both suites. `GATE=<path> tests/run` runs the fixture suite against another
  build.
- Invalid settings are rejected up front instead of failing halfway:
  `OMARCHY_PLUGIN_GATE_TIMEOUT` and `OMARCHY_PLUGIN_GATE_MAX_PATCH` must be
  positive whole numbers (the timeout no longer accepts `timeout(1)` suffixes
  such as `7m`), and `OMARCHY_PLUGIN_GATE_NOTIFY` must be `all`, `ready` or
  `none`.
- Argument errors are reported by `argparse`, so their wording differs; they
  still exit 1. An unknown `-p` name prints one error instead of two.
- `held` takes its reasons from the candidate's own verdict rather than from
  whichever review directory changed last, and a review marker's note reads
  `update from <base>` (it was `update<base>`).
- The reviewer's stdin is `/dev/null`, as it already was under the timer.
- Tripwire hooks quote their paths, create the state directory before logging
  to it, and pass the gate root and state directory of the run that installed
  them as `--root` and `--state`, so a hook reviews with the same paths whatever
  the environment of the `git pull`. Hooks written by 0.2.0, or with a
  different root or state, are out of date: `check`, `approve` and `update`
  rewrite them, and `doctor` reports them until `doctor --fix` does.
- Invalid setting messages name the option, variable or config key that
  supplied the value, for example `--timeout must be a positive whole number of
  seconds`.
- A relative `XDG_CONFIG_HOME` or `XDG_STATE_HOME` is ignored, as the XDG Base
  Directory specification requires, and the default under `~` is used instead.
- The reviewer model is best pinned in the config file, which the nightly check
  reads too; the service's commented `Environment=` line now only overrides it
  for unattended runs.

### Fixed

- An error in the middle of a review could be ignored, because bash disables
  `set -e` inside a function called from an `if`. A failed `git diff`, for
  example, left an empty patch for the reviewer. Any error during a review is
  now a `REVIEW FAIL` that records the error.
- When the reviewer exited non-zero after printing `REVIEW PASS`, the verdict
  file still began with `REVIEW PASS`, so `status` and `approve` showed a pass.
  The first line is now `REVIEW FAIL`, followed by the failure and the
  reviewer's ignored answer.
- A reviewer timeout now kills the reviewer's whole process group, including
  anything it spawned, and the verdict says it timed out.
- File names come from NUL-separated git output instead of quoted text. Paths
  with newlines, tabs, quotes or non-UTF-8 bytes are matched against the
  protected-path list as they really are, and are escaped in findings, so a
  file name can no longer forge extra lines in `findings.txt` or the prompt.
- A plugin's `.gitattributes` can no longer hide code: diffs and archives ignore
  attributes, so `*.qml -diff` does not reduce a change to "Binary files
  differ", and `export-ignore`/`export-subst` cannot alter the tree that is
  validated. The user's git config (`color.ui=always`, `diff.noprefix`, external
  diff drivers, textconv) no longer changes the patch either.
- The candidate tree is extracted for validation with Python's `data` tar
  filter, so links that point outside it are a hard failure instead of being
  followed.
- A candidate whose `manifest.json` is missing or not a JSON object is a hard
  failure even when `omarchy` is not on `PATH`, as are an `entryPoints` that is
  not an object and entry points that are not strings.
- git variables set for hooks (`GIT_DIR`, `GIT_INDEX_FILE` and the rest of
  `git rev-parse --local-env-vars`) are removed from every child process, so the
  tripwire always acts on the repository it was asked about.
- `approve --sha` passes the commit to git after `--end-of-options`, so it
  cannot be read as an option.
- State files (markers, waivers, `held`, evidence) are written atomically, and
  newlines in log messages, waiver reasons and marker notes are flattened so
  one event stays one line.

## [0.2.0] - 2026-10-28

### Added

- `approve <name>`: a one-time human approval for a candidate the gate held
  back. It prints the verdict, structural results and patch path, asks for a
  reason (an empty one is allowed; `--reason` skips the prompt), then moves
  `gate-approved`. The waiver is written to `waived/<sha>` with the date, user,
  reason, base commit and patch blob hash; the failed verdict is kept. Supports
  `--sha`, `--show` and `-n`/`--dry-run`. `status` reports waived approvals,
  `update` accepts a waiver in place of a review marker, and there is a
  `mise run approve` task.
- Structural findings: checks that often fire on legitimate code no longer fail
  the review on their own. Protected paths, binaries outside common asset
  types, executables without a shebang, manifest `kinds`/`entryPoints` changes,
  and download-and-execute lines are now numbered findings (`F1`, `F2`, …)
  handed to the reviewer with the patch, recorded in
  `reviews/<short-sha>/findings.txt`.
- The reviewer must answer each finding with exactly one
  `Fn CLEARED <reason>` line. A `REVIEW PASS` with a finding unanswered,
  answered twice, `CONFIRMED`, cleared without a reason, or an answer to a
  finding that does not exist is recorded as `REVIEW FAIL`.
- Passes that cleared findings write `reviews/<short-sha>/cleared` with each
  finding and the reviewer's reason. `check`, `status`, `add`, the log and the
  notification all call them out.
- More than 40 findings in one candidate is a hard failure.
- The reviewer must prove it saw the whole patch. The copy it receives,
  `reviews/<short-sha>/patch.review`, ends with a line carrying a random code
  word generated for each run and kept out of the prompt; the reviewer must
  answer `SEEN <word>`. A `REVIEW PASS` without the right word is recorded as
  `REVIEW FAIL`, and a `REVIEW FAIL` without it says the reviewer never saw
  the whole patch.
- A patch that is not valid UTF-8 is a hard structural failure naming the
  offending files. OpenCode does not hand such a file to the model as text, so
  the reviewer used to see no code at all and blame the patch size.
- `doctor` reports an installed reviewer agent that differs from the one in the
  repository.

### Changed

- The default gate root (`OMARCHY_PLUGIN_GATE_ROOT`) is now
  `~/Work/omarchy-plugins/`.
- Hard structural failures, which still skip the model, are now limited to an
  oversized patch, a patch that is not valid UTF-8, a manifest `id` change or
  unreadable manifest, a manifest that does not validate, entry points that
  escape the plugin directory or name a missing file, and too many findings.
- The default `OMARCHY_PLUGIN_GATE_MAX_PATCH` is now 2 MiB (was 512 KiB),
  sized for a reviewer model with a 1M-token context. Set it lower for smaller
  models.
- The `plugin-reviewer` agent has a section on judging findings and a new output
  format, and is installed verbatim; the state path is no longer rendered into
  it. Re-run `mise run install`.
- The reviewer runs from the candidate's review directory instead of the whole
  state directory, and may read, glob and grep only there. It gets 40 steps
  (was 8) and is told to page through `./patch.review` if the attachment is
  missing or cut off.

### Fixed

- The reviewer's `read`, `glob` and `grep` permissions never matched anything:
  OpenCode V2 matches `read` against a path relative to the working directory
  and `glob`/`grep` against the pattern, not an absolute state path. Every tool
  call was denied, so a reviewer that could not use the attachment had no way
  to read the patch.
- The entry-point "missing file" check and `omarchy plugin validate` now
  inspect the candidate commit rather than the clone's checkout. Before, a new
  entry-point file was always reported missing and the manifest was validated at
  the wrong revision.
- The entry-point escape check matches `..` path segments only, so a name such
  as `foo..qml` is no longer flagged.

## [0.1.0] - 2026-10-27

Initial release.

### Added

- `omarchy-plugin-gate` with `add`, `check`, `update`, `status` and `doctor`.
  Upstream changes are fetched into a clone under `~/Code/omarchy-plugins/`,
  reviewed, and staged on `refs/heads/gate-approved`. The installed copy's
  origin is the clone, so `omarchy plugin update` can only reach approved
  commits.
- Structural pre-checks with no model involved: protected paths, unexpected
  binaries, executables without a shebang, manifest identity changes, entry
  points, manifest validation, download-and-execute lines, and a patch size
  limit.
- A read-only `plugin-reviewer` OpenCode agent that is deny-by-default, runs
  from the state directory, and fails closed on a crash, timeout or missing
  verdict.
- An evidence trail under `~/.local/state/omarchy-plugin-gate/<name>/`.
- A `post-merge` tripwire that reviews out-of-band upstream merges and rolls
  them back, leaving local commits alone.
- A nightly systemd user timer for `check`, desktop notifications, mise tasks,
  install and uninstall scripts, and a fixture test suite.

[Unreleased]: https://github.com/haplo/omarchy-plugin-gate/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/haplo/omarchy-plugin-gate/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/haplo/omarchy-plugin-gate/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/haplo/omarchy-plugin-gate/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/haplo/omarchy-plugin-gate/releases/tag/v0.1.0
