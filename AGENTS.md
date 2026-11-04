# AGENTS.md

Review-before-update gate for Omarchy shell plugins. The core invariant: an
installed plugin may only move to a commit that passed structural checks and a
read-only model review. Everything here is the machinery for that promise.

Read `README.md` and `docs/` for the user-facing model (`docs/how-it-works.md`
for paths, state layout and the tripwire; `docs/review.md` for the checks;
`docs/configuration.md` for settings). This file is for changing the code.

## Layout

- `bin/omdall` — launcher run by the system `python3 -I`. It puts
  `src/` on the import path and calls `cli.main`. Hooks and the systemd unit
  call this exact file, so its path is part of the installed wiring.
- `src/omdall/` — the CLI. Start at `cli.py` (subcommands `add`, `adopt`,
  `check`, `approve`, `update`, `status`, `reviews`, `doctor`, and the hidden
  `_post-merge` hook entry point), then:
  - `config.py` — every setting, read once from the options, the environment
    and the TOML config file (`$XDG_CONFIG_HOME/omdall/config.toml`),
    in that order of priority.
  - `proc.py` — the only module that starts processes.
  - `git.py` — `Repo` wrapper; diffs and NUL-separated change records.
  - `mechanics.py`, `patterns.py` — structural checks (hard failures, findings,
    hints) as pure functions, plus one `check()` against git.
  - `reviewer.py` — prompt, opencode run, and `decide()`, which turns the
    reviewer's output into a verdict.
  - `review.py` — one candidate end to end; the fail-closed boundary.
  - `state.py` — markers, waivers, held, evidence directories, log.
  - `activity.py` — `activity.json`, the change signal and live progress for
    front ends. Display data only: nothing in the gate may read it to decide
    anything, and a failed write never fails a run.
  - `results.py` — the per-plugin result records (`PluginResult`,
    `DoctorResult`, `Report`) behind the action commands' `--json`.
  - `install.py` — first install of an approved commit (`omarchy plugin add`
    from the clone, then enable), shared by `add` and `update -p`.
  - `hooks.py`, `notify.py`, `plugins.py`, `context.py`, `commands/*.py`.
- `agents/omdall-reviewer.md.in` — reviewer agent, installed verbatim. The
  agent is deny-all except `read`/`glob`/`grep`; its scope comes from the
  directory the gate runs it in plus the `external_directory` deny. In OpenCode
  V2, `glob` and `grep` rules match the pattern, not the search path, and
  `read` rules match a path relative to the working directory, so do not write
  absolute path rules for them. `doctor` flags an installed copy that differs.
- `scripts/install.sh`, `scripts/uninstall.sh` — symlink the command, render the
  agent, copy `config.example.toml` when there is no config file (never
  overwriting one), install units/timer, and add/remove tripwires. Idempotent;
  rerun after changing the agent template or state path. They get the root and
  state from `scripts/paths.py`, which uses `config.py`, so the config file
  applies to them too.
- `completions/` — bash, zsh and fish completion scripts, hand-written and
  linked into `$XDG_DATA_HOME` by `install.sh` (`uninstall.sh` removes only
  links into this repository). They ask the hidden `_complete` command for
  plugin names and the held commit. A new command or option goes into all
  three; `tests/unit/test_completions.py` fails otherwise, and `mise run lint`
  syntax-checks the files when zsh and fish are installed.
- `docs/` — user documentation, one page per topic; `README.md` stays short
  and links there.
- `config.example.toml` — every setting commented out at its default. A unit
  test uncomments it and checks the result equals the built-in defaults.
- `systemd/` — nightly `check` service and timer. `%h` paths are rewritten by
  `install.sh`.
- `tests/run` — fixture suite (bash, needs `jq`), the end-to-end contract.
  Runs each `tests/suites/<name>.sh` in its own subshell against a fresh
  fixture under `<tmp>/<name>/`: throwaway upstreams and clones built from
  `tests/plugin/`, and the stubs in `tests/stubs/` (`opencode`, `omarchy` and
  friends) first on `PATH`. Helpers live in `tests/lib/`: `assert.sh` (`eq`,
  `has`, `assert`, `refute`), `fixture.sh` (`setup_env`, `make_upstream`,
  `demo_clone`, `demo_approved`, `install_copy`) and `gate.sh` (`ap`, `vdir`,
  `commit_upstream`, `case_*`). No network, no real model, no real plugin
  install. `tests/run approve hooks` runs only those suites;
  `GATE=<path> tests/run` runs it against another build.
- `tests/unit/` — pytest unit tests; `support.py` builds scratch git repos.
- `pyproject.toml`, `uv.lock` — development tools (pytest, ruff, ty) and their
  config. There is no build backend: the project is never installed.
- `mise.toml` — the public task interface: `install`, `uninstall`, `check`,
  `update`, `status`, `reviews`, `doctor`, `sync`, `test`, `lint`, `fmt`. It
  pins `uv`.

Runtime dependencies: `python3` 3.14+ (standard library only), `git`, and
`opencode` and `omarchy` on `PATH` (without `omarchy`, validation fails
closed). No third-party Python packages at runtime; this runs on
stock Omarchy machines. Development dependencies go in the `dev` group of
`pyproject.toml` and are locked in `uv.lock`.

## Commands

```sh
mise run sync          # once: pytest, ruff, ty into .venv
mise run test          # unit tests + fixture suite
mise run test:unit     # uv run pytest
mise run test:fixture  # tests/run [--keep] [suite ...]; --keep keeps the fixture
mise run lint          # ruff format --check, ruff check, ty check, shell syntax
mise run fmt           # ruff format + safe fixes
```

There is no build step. `mise run install` mutates the developer's actual
config, timer, and hooks — do not run it to verify a change. Use the fixture
suite instead.

When a fixture test fails, the fixture is kept automatically, its path is
printed, and the failed checks are listed with their suite. Suites never share
state: each starts from `demo_clone` (unreviewed), `demo_approved` (initial
import approved) or nothing, adds `install_copy` when it needs the installed
copy, and may change exports and the private git config freely. Put a new
check in the suite it belongs to, or add a suite file — the runner picks up
every `tests/suites/*.sh`. Within a suite, cases reset upstream to the last
approved commit via `reset_upstream`, so new cases should follow the existing
`case_hard`/`case_finding`/`case_uncleared` and `commit_upstream` patterns, and
use `assert`/`refute` rather than `[[ … ]] && ok … || no …`.

Unit tests must never reach a real `opencode` or `omarchy`: put a stub first on
`PATH` or monkeypatch the call. `/usr/bin/opencode` may exist on the machine.

## Invariants (do not weaken)

- **Fail closed.** No verdict line, reviewer crash/timeout/non-zero exit,
  malformed manifest, oversized patch, or anything unrecognised means
  `REVIEW FAIL`. Never turn a missing signal into a pass. `review.review()`
  catches every exception and records `REVIEW FAIL`; keep review logic inside
  it, and let `proc.run` raise on unexpected exits instead of swallowing them.
- **The reviewer proves it saw the whole patch.** `patch.review` is the patch
  plus a last line with a fresh random code word that never appears in the
  prompt. A verdict without a matching `SEEN <word>` line is `REVIEW FAIL`
  (a FAIL keeps its reasons and gains a note). Keep the word random per run and
  out of the prompt, and keep `seen_code` to cosmetic tolerance only.
- **Hard structural failures never reach the model.** `mechanics.check` runs
  first; tests assert the stub reviewer is not invoked for those cases. Only
  checks the model cannot judge, that protect the gate's own bookkeeping, or
  that match something no plugin has a legitimate use for (patch size, UTF-8
  encoding, binary code, native code, checkout filters and LFS, symlinks and
  submodules, `patterns.HARD_PATH` and executables in any protected path,
  manifest id, validity, entry points, finding count, an unreadable manifest)
  are hard. Protected paths some plugins do use (`patterns.DENY_PATH`) stay
  findings, and so does deleting any protected file. A patch that is not
  valid UTF-8 is never attached as text by OpenCode, so the reviewer would see
  no code at all; a file git treats as binary reaches it as "Binary files
  differ", so a binary with a code suffix or name, an entry point, an
  executable, or ELF/native library is hard, while other binaries and assets
  whose contents do not match their type are findings. A `filter` attribute
  anywhere in the tree, a `.lfsconfig`, or a changed LFS pointer is hard
  because a checkout would write something other than the reviewed blob. The
  id must be a valid plugin id (`patterns.valid_plugin_id`, checked by the
  gate itself), and `plugins.manifest_id_of` returns `""` for anything else,
  so no path is ever built from a bad id. `validate_tree` without `omarchy` on
  `PATH` is a hard failure, never a skip.
- **Every structural finding must be explicitly cleared.** Softer checks become
  numbered findings in the prompt. A `REVIEW PASS` counts only if each finding
  has exactly one `Fn CLEARED <reason>` line; missing, duplicate, `CONFIRMED`,
  reasonless, or unknown answers turn it into `REVIEW FAIL`. Do not loosen the
  parser in `finding_problems` beyond cosmetic tolerance.
- **`refs/heads/gate-approved` is authoritative.** `check` advances it only
  after a pass or a recorded one-time waiver; `update` refuses an approved
  commit with neither `<state>/<name>/reviewed/<sha>` nor
  `<state>/<name>/waived/<sha>`. Local work must never be rewritten by the
  gate.
- **The installed copy must track the gate clone.** Its `origin` points at
  `~/Work/omarchy-plugins/<name>`; that is what stops plain
  `omarchy plugin update` from bypassing review. `doctor` checks this.
- **Reviewer isolation.** Run the reviewer from the candidate's review
  directory (`reviews/<short-sha>/`), never the plugin checkout, and pass
  `patch.review` with `--file`. A hostile `.opencode/` or `AGENTS.md` in the
  diff must not be loadable. Keep the agent's permissions deny-by-default, with
  reads, globs and greps confined to its working directory. The plugin's
  `.gitattributes` is refused or ignored, never trusted: diffs, archives and
  the gate's own merges and resets run with `no_attributes=True`
  (`GIT_ATTR_SOURCE` set to the empty tree), so no plugin attribute can hide
  code or run a filter driver on checkout.
- **Tripwire scope.** The `post-merge` hook reviews only commits reachable from
  upstream and rolls those back; commits authored locally are left alone. The
  hook is a net, not the gate — do not move primary enforcement into it. The
  hook passes its plugin name, and the tripwire takes the installed copy's id
  from the approved commit (`plugins.approved_manifest_id`); never work out
  the plugin or its id from the merged working tree. Hooks are written only
  inside the repository's common git directory (never into a `core.hooksPath`
  elsewhere) and only over a hook the gate wrote (`hooks.hook_target`).
- **Evidence is written before decisions are made.** `patch`, `patch.review`,
  `mech.txt`, `findings.txt`, `hints.txt`, `review.txt`, `verdict`, and (for passes that
  cleared findings) `cleared` under
  `<state>/<name>/reviews/<short-sha>/` are the audit trail. Keep them complete
  and readable after both passes and failures.
- **Manual approval is explicit and recorded.** `approve` may waive a failed
  review for one commit, but only after printing the evidence and collecting a
  reason (possibly empty). Keep the failed verdict, write the waiver under
  `<state>/<name>/waived/<sha>` with date/user/base/patch hash, and never make
  the path automatic or plugin-wide. The patch shown and hashed is the diff
  from the current `gate-approved` to the candidate, not the stored evidence.

## Conventions

- Python 3.14, standard library only, fully typed; `ruff` and `ty` must pass.
  Frozen dataclasses for records, `Path` for paths. Keep checks and parsing as
  pure functions on plain data and do the git and file work around them, so
  they can be unit-tested without a repository.
- Processes start only through `proc.run`, `proc.run_quiet` or
  `proc.run_supervised`: a fixed argument list, never `shell=True`, and a
  scrubbed environment (no `GIT_DIR` and friends from hooks). Expected non-zero
  exits use `check=False`.
- git goes through `Repo`. Diffs use the fixed `_DIFF_OPTS` and ignore
  `.gitattributes`; file lists come from `-z` output; prefer plumbing over
  porcelain. User-supplied revs go through `Repo.rev`/`Repo.commit`, which add
  `--end-of-options`. `Repo.update_ref` takes the value the caller read
  (`None`: the ref must not exist yet), so a ref never moves from a state the
  run did not see. A merge or checkout the gate runs itself passes
  `no_hooks=True` as well as `no_attributes=True`.
- Commands that write state run under `State.lock()`, taken once in
  `cli.dispatch` through `cli._locked` (`add`, `adopt`, `approve` without
  `--dry-run`, `check`, `update`, `doctor --fix`, `_post-merge`), which also
  writes the start and end of the run to `activity.json`. The lock is not
  reentrant, even within one process: never take it again below `dispatch`,
  and never let a git command the gate runs under it start a hook (the
  tripwire would wait for it). Commands report their phase with
  `ctx.progress(phase, plugin, index, total)`; the phases are a closed set
  (`activity.PHASES`), documented in `docs/scripting.md`.
- Anything from a plugin (paths, manifest values, reviewer text) that lands in
  a line-oriented file, the log or the prompt goes through `output.printable`
  or `state.one_line` first, so it cannot forge extra lines.
- State files are written with `state.write_atomic`. Their formats are shared
  with earlier releases; do not change them without a migration.
- User-facing output goes through `output.say`, `info`, `ok`, `bad`, `warn` and
  `indented`; failures raise `GateError`, which prints
  `omdall: <message>` to stderr and exits with its `exit_code`
  (1; `Busy`, raised by `State.lock(wait=False)`, is 75). Raise the subclass
  whose `code` names the failure (`NotFound`, `RefusedUrl`, `NameTaken`, …);
  `--json` reports that `code`, and callers rely on it rather than on the
  message. A new code is documented in `docs/scripting.md`.
- `--json` (`status`, `reviews`, and the action commands `add`, `adopt`,
  `check`, `update`, `doctor`) and `activity.json` are the public interface
  for other programs (a front end, scripts); the other state files are not.
  The records (`PluginRecord`, `ReviewRecord`, `PluginResult`) also drive the
  text output, so the two cannot disagree. Action commands return a `Report`;
  with `--json`, `dispatch` sends everything else they print to stderr.
  `outcome` values and `status --json` `features` are closed sets: add to them
  only together with the docs. JSON goes through `output.emit_json`, which adds
  `"schema"`; only ever add fields, and bump `JSON_SCHEMA` for a removal or a
  change of meaning. With `--json` nothing else may reach stdout.
- Shell (`scripts/`, `tests/`, the hook text) stays bash with
  `set -euo pipefail` and two-space indent. `tests/run` intentionally uses
  `set -uo pipefail` (without `-e`) because it inspects non-zero exits; the
  files in `tests/lib/` and `tests/suites/` are sourced by it and inherit that.
- A new setting is a field on `config.Overrides`, which gives it the option
  `--<name>`, the variable `OMDALL_<NAME>` and the config file key
  `<name>` (dashes, like the option); the option wins over the variable, which
  wins over the file. It gets a default in `Config.from_env`, a commented-out
  line at that default in `config.example.toml`, a row in the settings table
  in `docs/configuration.md`, a line in `cli.USAGE`, and an entry in the
  option list of all three completion scripts. There are no unprefixed
  aliases.
- Unit tests must never read the developer's config file: `conftest.py` points
  `XDG_CONFIG_HOME` at a scratch directory, and tests that build an environment
  by hand should set it too.
- A user-visible change touches all three: `cli.USAGE`, the docs
  (`README.md` or the matching page in `docs/`), and a test. For a release,
  bump `__version__` in `src/omdall/__init__.py` and `version` in
  `pyproject.toml` (a unit test checks they match), and add a `CHANGELOG.md`
  entry.
- Style: direct, lowercase commands, plain prose, no filler. Emit `✓`/`✗` only
  through the existing helpers.
- Keep the diff focused. The user's working clones, state directory, and
  installed plugins are not part of this repository; never clean, reset, or
  "fix" them while working on the gate.
