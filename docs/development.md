# Development

The code is Python in `src/omdall/`, started by `bin/omdall`. There is no
build step. Contributor rules and invariants are in
[`AGENTS.md`](../AGENTS.md).

```sh
mise install            # uv
mise run sync           # pytest, ruff and ty into .venv
mise run lint           # format check, ruff, ty, shell syntax
mise run fmt            # format and apply safe fixes
mise run test           # unit tests and fixture suite
mise run test:unit
mise run test:fixture   # or: tests/run [--keep] [suite ...]
```

Don't run `mise run install` to test a change: it modifies your real config,
timer and hooks. Use the fixture suite instead.

## Unit tests

`tests/unit/` (pytest) tests the pure pieces on their own: path and pattern
checks, git output parsing with awkward file names, every way a reviewer
answer can fail, state file formats, the JSON records, the lock, the shell
completions matching the parser, and the fail-closed paths (git errors,
reviewer crashes and timeouts).

## Fixture suite

`tests/run` (bash, needs `jq`) is the end-to-end test. Each suite in
`tests/suites/` runs against throwaway repositories, using a stub reviewer and
stub `omarchy` commands from `tests/stubs/`. It needs no network, no real
model and no real plugin install. To run only some suites, name them:
`tests/run approve hooks`. A failed suite keeps its fixture and prints its
path.

It covers the whole user-facing behaviour: every hard failure (and that the
model is not called), every kind of finding, reviewer failures and the code
word, settings priority, install and uninstall, completions, updates and
refusals, tripwire rollbacks, notifications, approvals, `add`, the JSON
output, and `--no-wait`.
