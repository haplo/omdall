# Settings: options beat the environment, which beats the config file.

demo_approved

printf '\n== model override ==\n'
commit_upstream 'printf "// p\n" >> Widget.qml' model
: >"$STUB_LOG"
OMDALL_MODEL=venice/whatever "$GATE" check >/dev/null 2>&1
has "$STUB_LOG" '-m venice/whatever' 'model passed to the reviewer'

printf '\n== options beat the environment ==\n'
commit_upstream 'printf "// options\n" >> Widget.qml' options
: >"$STUB_LOG"
OMDALL_ROOT=$B/nowhere OMDALL_STATE=$B/wrong-state \
  OMDALL_MODEL=venice/env OMDALL_TIMEOUT=soon \
  "$GATE" --root "$B/root" --model venice/flag check --state "$B/state" --timeout 60 >/dev/null 2>&1
eq 'check exits 0' "$?" 0
eq '--root finds the clone' "$(ap)" "$(upstream_sha)"
assert '--state receives the marker' test -f "$B/state/demo/reviewed/$(ap)"
refute 'environment state unused' test -e "$B/wrong-state"
has "$STUB_LOG" '-m venice/flag' '--model passed to the reviewer'

printf '\n== config file ==\n'
conf=$B/cfg/omdall/config.toml
mkdir -p "$(dirname "$conf")"
printf 'model = "venice/from-file"\n' >"$conf"
commit_upstream 'printf "// config\n" >> Widget.qml' config
: >"$STUB_LOG"
"$GATE" check >/dev/null 2>&1
has "$STUB_LOG" '-m venice/from-file' 'model read from the config file'
commit_upstream 'printf "// config env\n" >> Widget.qml' 'config env'
: >"$STUB_LOG"
OMDALL_MODEL=venice/from-env "$GATE" check >/dev/null 2>&1
has "$STUB_LOG" '-m venice/from-env' 'environment beats the config file'
eq 'config file run approved' "$(ap)" "$(upstream_sha)"
printf 'modle = "typo"\n' >"$conf"
out=$("$GATE" status 2>&1)
eq 'bad config file exits 1' "$?" 1
has <(printf '%s' "$out") "unknown setting 'modle' in $conf" 'bad config file explained'
