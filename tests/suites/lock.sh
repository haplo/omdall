# One run at a time: commands that write wait for the state lock, commands that
# only read do not, and the gate's own merges never start the tripwire (which
# would wait for the lock the gate holds).

demo_approved
install_copy

hold_lock() { # hold_lock <seconds>: hold the lock in the background; sets $holder
  rm -f "$B/locked"
  python3 -c '
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT)
fcntl.flock(fd, fcntl.LOCK_EX)
open(sys.argv[2], "w").close()
time.sleep(float(sys.argv[3]))
' "$B/state/gate.lock" "$B/locked" "$1" &
  holder=$!
  local i
  for i in $(seq 100); do
    [[ -e $B/locked ]] && return 0
    sleep 0.05
  done
  no 'fixture: lock holder started'
}

printf '\n== check waits for another run ==\n'
hold_lock 1
commit_upstream 'printf "// waited\n" >> Widget.qml' waited
out=$(timeout 60 "$GATE" check 2>&1)
eq 'check succeeded after waiting' "$?" 0
has <(printf '%s' "$out") 'waiting for another run to finish' 'check said it was waiting'
refute 'the other run had finished' kill -0 "$holder" 2>/dev/null
eq 'check reviewed after waiting' "$(ap)" "$(upstream_sha)"
wait "$holder"

printf '\n== reads do not wait ==\n'
hold_lock 60
for cmd in status doctor 'approve demo --dry-run'; do
  # shellcheck disable=SC2086 # the command and its arguments are split on purpose
  out=$(timeout 10 "$GATE" $cmd 2>&1)
  rc=$?
  refute "$cmd was not stopped by the timeout" test "$rc" = 124
  refute "$cmd did not wait" grep -q 'waiting for another run' <(printf '%s' "$out")
done
out=$(timeout 2 "$GATE" doctor --fix 2>&1)
eq 'doctor --fix waits' "$?" 124
busy=$(timeout 10 "$GATE" status --json 2>/dev/null | jq -r .busy)
eq 'status --json reports the run in progress' "$busy" true
kill "$holder"
wait "$holder" 2>/dev/null
busy=$("$GATE" status --json 2>/dev/null | jq -r .busy)
eq 'status --json: not busy once it finished' "$busy" false

printf '\n== --no-wait exits 75 and does nothing ==\n'
base=$(ap)
commit_upstream 'printf "// no wait\n" >> Widget.qml' 'no wait'
reviews_before=$(ls "$B/state/demo/reviews" | wc -l)
n0=$(invocations)
hold_lock 60
for cmd in check update 'doctor --fix' 'approve demo --reason x'; do
  # shellcheck disable=SC2086 # the command and its arguments are split on purpose
  out=$(timeout 10 "$GATE" $cmd --no-wait 2>&1)
  eq "$cmd --no-wait exits 75" "$?" 75
  has <(printf '%s' "$out") 'another omdall run is in progress' "$cmd --no-wait says why"
  refute "$cmd --no-wait did not wait" grep -q 'waiting for another run' <(printf '%s' "$out")
done
kill "$holder"
wait "$holder" 2>/dev/null
eq 'no-wait: gate-approved unchanged' "$(ap)" "$base"
eq 'no-wait: no review evidence written' "$(ls "$B/state/demo/reviews" | wc -l)" "$reviews_before"
eq 'no-wait: reviewer not called' "$(invocations)" "$n0"
timeout 60 "$GATE" check --no-wait >/dev/null 2>&1
eq 'check --no-wait runs when the gate is free' "$?" 0
eq 'check --no-wait reviewed the commit' "$(ap)" "$(upstream_sha)"

printf '\n== the gate'"'"'s own merges skip the tripwire ==\n'
"$GATE" doctor --fix >/dev/null 2>&1
assert 'tripwire in the clone' test -x "$B/root/demo/.git/hooks/post-merge"
assert 'tripwire in the installed copy' test -x "$idir/.git/hooks/post-merge"
commit_upstream 'printf "// own merge\n" >> Widget.qml' 'own merge'
rm -f "$B/state/hooks.log"
timeout 60 "$GATE" check >/dev/null 2>&1
eq 'check advanced the clone' "$(git -C "$B/root/demo" rev-parse HEAD)" "$(ap)"
timeout 60 "$GATE" update >/dev/null 2>&1
eq 'update moved the installed copy' "$(git -C "$idir" rev-parse HEAD)" "$(ap)"
refute 'no tripwire ran' test -e "$B/state/hooks.log"
