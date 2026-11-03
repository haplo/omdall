# The post-merge tripwire: rolls back rejected upstream commits, never local work.

demo_approved

printf '\n== hooks leave local work alone ==\n'
"$GATE" doctor --fix >/dev/null 2>&1
( cd "$B/root/demo" && git checkout -q -b feature && printf '// local work\n' > Local.qml &&
  git add -A && git -c commit.gpgsign=false commit -qm 'local feature' &&
  git checkout -q main && git merge -q --ff-only feature )
local_sha=$(git -C "$B/root/demo" rev-parse HEAD)
refute 'own commit not reviewed' test -f "$B/state/demo/reviewed/$local_sha"
eq 'own commit kept' "$(git -C "$B/root/demo" rev-parse HEAD)" "$local_sha"
git -C "$B/root/demo" reset -q --hard origin/main

printf '\n== tripwire ==\n'
install_copy
"$GATE" doctor --fix >/dev/null 2>&1
assert 'hook in the clone' test -x "$B/root/demo/.git/hooks/post-merge"
assert 'hook in the installed copy' test -x "$idir/.git/hooks/post-merge"
has "$B/root/demo/.git/hooks/post-merge" "--root $B/root --state $B/state _post-merge" 'hook records root and state'
base=$(git -C "$B/root/demo" rev-parse HEAD)
commit_upstream 'printf "// NEEDS-HUMAN\n" >> Widget.qml' 'bad pull'
jq '.name = "my local edit"' "$B/root/demo/manifest.json" >"$B/m" && mv "$B/m" "$B/root/demo/manifest.json"
STUB_FAIL_ON=NEEDS-HUMAN bash -c "cd '$B/root/demo' && git pull -q --ff-only origin main" >/dev/null 2>&1
eq 'rejected pull rolled back' "$(git -C "$B/root/demo" rev-parse HEAD)" "$base"
has "$B/root/demo/manifest.json" 'my local edit' 'uncommitted edit survives the rollback'
has "$B/state/gate.log" "hook: rolled back" 'rollback logged'
git -C "$B/root/demo" checkout -q -- manifest.json
commit_upstream 'printf "// fine\n" >> Widget.qml' 'good pull'
good=$(git -C "$B/upstream" rev-parse HEAD)
OMDALL_ROOT=$B/nowhere OMDALL_STATE=$B/wrong-state \
  bash -c "cd '$B/root/demo' && git pull -q --ff-only origin main" >/dev/null 2>&1
eq 'clean pull kept' "$(git -C "$B/root/demo" rev-parse HEAD)" "$good"
assert 'hook wrote a marker in its recorded state' test -f "$B/state/demo/reviewed/$good"
refute 'hook ignores the environment paths' test -e "$B/wrong-state"
has "$idir/.git/hooks/post-merge" '_post-merge demo "$top"' 'hook names its plugin'

base=$(ap)
reset_upstream "$base"
commit_upstream 'jq ".id = \"selftest.other\"" manifest.json > m && mv m manifest.json' 'change the id'
git -C "$B/root/demo" fetch -q origin
renamed=$(upstream_sha)
before=$(git -C "$idir" rev-parse HEAD)
: >"$OMARCHY_LOG"
n0=$(invocations)
bash -c "cd '$idir' && git pull -q --ff-only origin refs/remotes/origin/main" >/dev/null 2>&1
eq 'id change: installed copy rolled back' "$(git -C "$idir" rev-parse HEAD)" "$before"
has "$B/state/demo/reviews/${renamed:0:12}/verdict" 'manifest id changed' 'id change: reviewed by the hook'
eq 'id change: reviewer skipped' "$(invocations)" "$n0"
has "$OMARCHY_LOG" 'plugin disable selftest.demo' 'id change: approved id disabled'

printf '\n== a post-merge hook of your own is never replaced ==\n'
reset_upstream "$(ap)"
hook=$(realpath "$B/root/demo/.git/hooks")/post-merge
printf '#!/bin/sh\necho mine\n' >"$hook"
out=$("$GATE" doctor --fix 2>&1)
has <(printf '%s' "$out") "no tripwire in the clone: a post-merge hook of your own exists at $hook" \
  'doctor --fix reports the hook'
has <(printf '%s' "$out") 'tripwire in the installed copy' 'the installed copy keeps its tripwire'
commit_upstream 'printf "// own hook\n" >> Widget.qml' 'own hook'
out=$("$GATE" check 2>&1)
eq 'own hook: candidate approved' "$(ap)" "$(upstream_sha)"
has <(printf '%s' "$out") "could not install the tripwire in $B/root/demo: a post-merge hook of your own" \
  'check warns about the hook'
eq 'own hook untouched' "$(cat "$hook")" "$(printf '#!/bin/sh\necho mine')"
rm "$hook"

printf '\n== no tripwire under core.hooksPath ==\n'
mkdir -p "$B/shared-hooks"
shared=$(realpath "$B/shared-hooks")
git -C "$B/root/demo" config core.hooksPath "$shared"
out=$("$GATE" doctor --fix 2>&1)
has <(printf '%s' "$out") \
  "no tripwire in the clone: core.hooksPath is set ($shared), so the tripwire was not installed" \
  'doctor reports core.hooksPath'
commit_upstream 'printf "// hooks path\n" >> Widget.qml' 'hooks path'
out=$("$GATE" check 2>&1)
eq 'hooks path: candidate approved' "$(ap)" "$(upstream_sha)"
has <(printf '%s' "$out") "could not install the tripwire in $B/root/demo: core.hooksPath is set" \
  'check warns about core.hooksPath'
refute 'nothing written to the shared hooks directory' test -e "$shared/post-merge"
git -C "$B/root/demo" config --unset core.hooksPath
"$GATE" doctor --fix >/dev/null 2>&1
assert 'tripwire back once core.hooksPath is unset' grep -q '_post-merge demo' "$B/root/demo/.git/hooks/post-merge"
