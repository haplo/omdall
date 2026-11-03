# --json on the action commands, error codes, and activity.json: what a front
# end reads. stdout holds one JSON object and nothing else.

json_only() { # json_only <label> <stdout file>: one JSON object on stdout
  assert "$1: stdout is one JSON object" jq -e 'type == "object"' "$2" >/dev/null
}
outcome() { jq -r ".results[] | select(.name == \"$2\") | .outcome" "$1"; }
seq_of() { jq -r .seq "$B/state/activity.json" 2>/dev/null || printf 0; }

demo_approved
install_copy

printf '\n== check --json ==\n'
commit_upstream 'printf "// json ok\n" >> Widget.qml' 'json ok'
"$GATE" check --json >"$B/out" 2>"$B/err"
eq 'check --json exits 0' "$?" 0
json_only check "$B/out"
eq 'command' "$(jq -r .command "$B/out")" check
eq 'ok' "$(jq -r .ok "$B/out")" true
eq 'approved' "$(outcome "$B/out" demo)" approved
eq 'sha' "$(jq -r '.results[0].sha' "$B/out")" "$(upstream_sha)"
eq 'id' "$(jq -r '.results[0].id' "$B/out")" selftest.demo
eq 'summary ready' "$(jq -c .summary.ready "$B/out")" '["demo"]'
has "$B/err" 'demo: reviewing' 'progress lines go to stderr'
"$GATE" check --json >"$B/out" 2>/dev/null
eq 'up to date' "$(outcome "$B/out" demo)" up_to_date

commit_upstream 'printf "// NEEDS-JSON-HOLD\n" >> Widget.qml' 'json hold'
STUB_FAIL_ON=NEEDS-JSON-HOLD "$GATE" check --json >"$B/out" 2>/dev/null
eq 'held: exit status unchanged' "$?" 0
eq 'held' "$(outcome "$B/out" demo)" held
has <(jq -r '.results[0].message' "$B/out") 'REVIEW FAIL' 'held message has the verdict'
eq 'summary held' "$(jq -c .summary.held "$B/out")" '["demo"]'
"$GATE" approve demo --reason 'json' >/dev/null 2>&1

printf '\n== update --json ==\n'
"$GATE" update --json >"$B/out" 2>"$B/err"
eq 'update --json exits 0' "$?" 0
json_only update "$B/out"
eq 'installed' "$(outcome "$B/out" demo)" installed
eq 'summary is null' "$(jq -r .summary "$B/out")" null
"$GATE" update --json >"$B/out" 2>/dev/null
eq 'up to date' "$(outcome "$B/out" demo)" up_to_date
commit_upstream 'printf "// json dirty\n" >> Widget.qml' 'json dirty'
"$GATE" check >/dev/null 2>&1
printf 'x\n' >"$idir/scratch.txt"
"$GATE" update --json >"$B/out" 2>/dev/null
eq 'blocked' "$(outcome "$B/out" demo)" blocked_dirty
eq 'dirty files' "$(jq -c '.results[0].dirty' "$B/out")" '["scratch.txt"]'
rm "$idir/scratch.txt"
"$GATE" update >/dev/null 2>&1

printf '\n== doctor --json ==\n'
"$GATE" doctor --json >"$B/out" 2>/dev/null
json_only doctor "$B/out"
eq 'doctor problems are results' "$(jq -r '[.results[] | select(.ok == false)] | length > 0' "$B/out")" true
rm "$idir/.git/hooks/post-merge"
"$GATE" doctor --fix --json >"$B/out" 2>/dev/null
eq 'fixed hook reported' \
  "$(jq -r '.results[] | select(.check == "hook_installed") | "\(.ok) \(.fixed)"' "$B/out")" 'true true'

printf '\n== add --json ==\n'
make_upstream addme selftest.addme
"$GATE" add "$B/addme.git" --json >"$B/out" 2>"$B/err"
eq 'add --json exits 0' "$?" 0
json_only add "$B/out"
eq 'installed' "$(outcome "$B/out" addme)" installed
has "$B/err" 'Cloning' 'add progress on stderr'
make_upstream addheld selftest.addheld
STUB_FAIL_ON='A fixture widget' "$GATE" add "$B/addheld.git" --json >"$B/out" 2>/dev/null
eq 'held add exits 1' "$?" 1
eq 'held add outcome' "$(outcome "$B/out" addheld)" held
eq 'held add ok' "$(jq -r .ok "$B/out")" false
"$GATE" add "$B/addme.git" --json >"$B/out" 2>/dev/null
eq 'name taken exits 1' "$?" 1
eq 'name taken code' "$(jq -r .code "$B/out")" name_taken
"$GATE" add http://example.invalid/x --json >"$B/out" 2>/dev/null
eq 'refused url code' "$(jq -r .code "$B/out")" refused_url
"$GATE" check -p nope --json >"$B/out" 2>/dev/null
eq 'unknown plugin code' "$(jq -r .code "$B/out")" not_found
OMDALL_NOTIFY=sometimes "$GATE" check --json >"$B/out" 2>/dev/null
eq 'config code' "$(jq -r .code "$B/out")" config

printf '\n== busy ==\n'
python3 -c '
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT)
fcntl.flock(fd, fcntl.LOCK_EX)
open(sys.argv[2], "w").close()
time.sleep(60)
' "$B/state/gate.lock" "$B/locked" &
holder=$!
for i in $(seq 100); do [[ -e $B/locked ]] && break; sleep 0.05; done
for cmd in check update add doctor; do
  args=()
  [[ $cmd == add ]] && args=("$B/addme.git" --dir other)
  [[ $cmd == doctor ]] && args=(--fix)
  timeout 10 "$GATE" "$cmd" "${args[@]}" --no-wait --json >"$B/out" 2>/dev/null
  eq "$cmd busy exits 75" "$?" 75
  eq "$cmd busy code" "$(jq -r .code "$B/out")" busy
done
kill "$holder"
wait "$holder" 2>/dev/null

printf '\n== activity.json ==\n'
before=$(seq_of)
"$GATE" check >/dev/null 2>&1
after=$(seq_of)
assert 'check bumps seq' test "$after" -gt "$before"
eq 'not running afterwards' "$(jq -r .running "$B/state/activity.json")" null
eq 'last run' "$(jq -r .last_run.command "$B/state/activity.json")" check
assert 'last check recorded' jq -e '.last_check.finished' "$B/state/activity.json" >/dev/null
"$GATE" approve demo --dry-run >/dev/null 2>&1
"$GATE" status >/dev/null 2>&1
"$GATE" status --json >/dev/null 2>&1
"$GATE" reviews >/dev/null 2>&1
"$GATE" doctor >/dev/null 2>&1
eq 'read-only commands leave it alone' "$(seq_of)" "$after"

"$GATE" doctor --fix >/dev/null 2>&1
commit_upstream 'printf "// tripwire activity\n" >> Widget.qml' 'tripwire activity'
before=$(seq_of)
bash -c "cd '$B/root/demo' && git pull -q --ff-only origin main" >/dev/null 2>&1
assert 'the tripwire bumps seq' test "$(seq_of)" -gt "$before"
eq 'tripwire run recorded' "$(jq -r .last_run.command "$B/state/activity.json")" tripwire
eq 'tripwire not running afterwards' "$(jq -r .running "$B/state/activity.json")" null
