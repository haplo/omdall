# One-time manual approval of a held commit, and installing it.

demo_approved
install_copy

printf '\n== approve ==\n'
base=$(ap)
commit_upstream 'printf "// NEEDS-HUMAN-APPROVE\n" >> Widget.qml' 'approve me'
STUB_FAIL_ON=NEEDS-HUMAN-APPROVE "$GATE" check -p demo >/dev/null 2>&1
held=$(upstream_sha)
eq 'approve: candidate held' "$(head -1 "$B/state/demo/held")" "$held"
eq 'approve: gate-approved unchanged' "$(ap)" "$base"

out=$("$GATE" approve demo </dev/null 2>&1)
eq 'approve: no prompt without a terminal' "$?" 1
has <(printf '%s' "$out") 'no terminal for the reason prompt' 'refusal explained'

out=$("$GATE" approve -p demo -n 2>&1)
eq 'approve: dry run exits 0' "$?" 0
eq 'approve: dry run leaves gate-approved' "$(ap)" "$base"
eq 'approve: dry run leaves held' "$(head -1 "$B/state/demo/held")" "$held"
refute 'approve: dry run writes no waiver' test -f "$B/state/demo/waived/$held"
has <(printf '%s' "$out") 'dry run' 'approve: dry run announced'

out=$("$GATE" approve demo --sha "$held" --reason "checked the diff" --show 2>&1)
eq 'approve: exits 0' "$?" 0
eq 'approve: advances gate-approved' "$(ap)" "$held"
assert 'approve: waiver written' test -f "$B/state/demo/waived/$held"
has "$B/state/demo/waived/$held" 'reason: checked the diff' 'approve: reason kept'
has "$B/state/demo/waived/$held" "base: $base" 'approve: base kept'
has <(printf '%s' "$out") 'NEEDS-HUMAN-APPROVE' 'approve: --show printed the patch'
refute 'approve: held cleared' test -f "$B/state/demo/held"
refute 'approve: no fake review marker' test -f "$B/state/demo/reviewed/$held"

"$GATE" update -p demo >/dev/null 2>&1
eq 'approve: update installs the waiver' "$(git -C "$idir" rev-parse HEAD)" "$held"

base=$(ap)
commit_upstream 'printf "// NEEDS-HUMAN-APPROVE-2\n" >> Widget.qml' 'approve me too'
STUB_FAIL_ON=NEEDS-HUMAN-APPROVE-2 "$GATE" check -p demo >/dev/null 2>&1
held2=$(upstream_sha)
"$GATE" approve demo --reason "" >/dev/null 2>&1
eq 'approve: defaults to the held commit' "$(ap)" "$held2"
assert 'approve: empty reason allowed' grep -q '^reason: $' "$B/state/demo/waived/$held2"

git -C "$B/root/demo" update-ref refs/heads/gate-approved "$base"
n0=$(invocations)
"$GATE" check -p demo >/dev/null 2>&1
eq 'approve: check re-advances a waiver' "$(ap)" "$held2"
eq 'approve: check skips the reviewer for a waiver' "$(invocations)" "$n0"

out=$("$GATE" status -p demo 2>&1)
has <(printf '%s' "$out") 'waived by hand' 'status reports the waiver'

printf '\n== approve a structural hold ==\n'
commit_upstream 'printf "// a line long enough to cross a tiny limit\n" >> Widget.qml' 'structural approve'
n0=$(invocations)
OMDALL_MAX_PATCH=64 "$GATE" check -p demo >/dev/null 2>&1
held3=$(upstream_sha)
eq 'structural approve: candidate held' "$(head -1 "$B/state/demo/held")" "$held3"
"$GATE" approve demo --reason "I need this one" >/dev/null 2>&1
eq 'structural approve: advances gate-approved' "$(ap)" "$held3"
eq 'structural approve: reviewer never called' "$(invocations)" "$n0"
has "$B/state/demo/waived/$held3" 'reason: I need this one' 'structural approve: reason kept'

# The diff git would give for <base>..<sha>, with the gate's options.
gate_diff_blob() {
  git -C "$B/root/demo" diff --no-color --no-ext-diff --no-textconv \
    --src-prefix=a/ --dst-prefix=b/ -M "$1" "$2" | git hash-object --stdin
}
waiver_line() { grep "^$2: " "$B/state/demo/waived/$1" | cut -d' ' -f2; }

printf '\n== approve records the diff it lets through ==\n'
base=$(ap)
commit_upstream 'printf "// parent-of-held\n" >> Widget.qml' 'parent'
parent=$(git -C "$B/upstream" rev-parse HEAD)
commit_upstream 'printf "// NEEDS-HUMAN-MOVED\n" >> Widget.qml' 'moved base'
STUB_FAIL_ON=NEEDS-HUMAN-MOVED "$GATE" check -p demo >/dev/null 2>&1
moved=$(upstream_sha)
eq 'moved: candidate held' "$(head -1 "$B/state/demo/held")" "$moved"

out=$("$GATE" approve demo --sha "$parent" </dev/null 2>&1)
eq 'never reviewed: no approval without --show or --reason' "$?" 1
has <(printf '%s' "$out") 'has no review verdict; read the diff with --show' 'never reviewed: refusal explained'
eq 'never reviewed: gate-approved unchanged' "$(ap)" "$base"

out=$("$GATE" approve demo --sha "$parent" --reason 'read it on GitHub' 2>&1)
eq 'never reviewed: approved with a reason' "$(ap)" "$parent"
has <(printf '%s' "$out") 'the recorded review covered a different diff than this approval' \
  'never reviewed: warned'
eq 'never reviewed: patch-blob is the approved diff' "$(waiver_line "$parent" patch-blob)" \
  "$(gate_diff_blob "$base" "$parent")"
refute 'never reviewed: no evidence-blob' grep -q '^evidence-blob:' "$B/state/demo/waived/$parent"

out=$("$GATE" approve demo --reason 'base moved' --show 2>&1)
eq 'moved: approved' "$(ap)" "$moved"
has <(printf '%s' "$out") 'the recorded review covered a different diff' 'moved: warned'
has <(printf '%s' "$out") '+// NEEDS-HUMAN-MOVED' '--show prints the approved diff'
refute '--show leaves out what was approved before' grep -qF '+// parent-of-held' <(printf '%s' "$out")
eq 'moved: patch-blob is the approved diff' "$(waiver_line "$moved" patch-blob)" \
  "$(gate_diff_blob "$parent" "$moved")"
eq 'moved: evidence-blob is the reviewed patch' "$(waiver_line "$moved" evidence-blob)" \
  "$(git hash-object "$B/state/demo/reviews/${moved:0:12}/patch")"
