# The machine-readable contract: status --json and reviews --json print one
# JSON object on stdout and nothing else, failures included.

demo_approved
install_copy

printf '\n== status --json, installed ==\n'
first=$(ap)
out=$("$GATE" status --json 2>"$B/status.err")
eq 'status --json exits 0' "$?" 0
assert 'status --json stdout is one JSON object' jq -e 'type == "object"' <<<"$out" >/dev/null
assert 'status --json prints nothing on stderr' test ! -s "$B/status.err"
eq 'schema' "$(jq -r .schema <<<"$out")" 1
eq 'version' "$(jq -r .version <<<"$out")" "$("$GATE" --version)"
eq 'root' "$(jq -r .root <<<"$out")" "$B/root"
eq 'state dir' "$(jq -r .state <<<"$out")" "$B/state"
eq 'busy' "$(jq -r .busy <<<"$out")" false
eq 'one plugin' "$(jq '.plugins | length' <<<"$out")" 1
eq 'name' "$(jq -r '.plugins[0].name' <<<"$out")" demo
eq 'id' "$(jq -r '.plugins[0].id' <<<"$out")" selftest.demo
eq 'state installed' "$(jq -r '.plugins[0].state' <<<"$out")" installed
eq 'nothing next' "$(jq -r '.plugins[0].next' <<<"$out")" null
eq 'approved' "$(jq -r '.plugins[0].approved' <<<"$out")" "$first"
eq 'installed' "$(jq -r '.plugins[0].installed' <<<"$out")" "$first"
eq 'installed_dir' "$(jq -r '.plugins[0].installed_dir' <<<"$out")" "$idir"
eq 'clean copy' "$(jq -c '.plugins[0].dirty' <<<"$out")" '[]'
eq 'reviewed commit' "$(jq -r '.plugins[0].never_reviewed' <<<"$out")" false
eq 'latest review passed' "$(jq -r '.plugins[0].latest_review.passed' <<<"$out")" true
eq 'latest review approval' "$(jq -r '.plugins[0].latest_review.approval' <<<"$out")" reviewed
assert 'latest review patch exists' test -f "$(jq -r '.plugins[0].latest_review.files.patch' <<<"$out")"
assert 'features' jq -e '.features | index("attention") and index("activity")' <<<"$out" >/dev/null
eq 'nothing needs attention' "$(jq -c .attention <<<"$out")" '[]'
eq 'nothing pending' "$(jq -r '.plugins[0].pending' <<<"$out")" 0
eq 'update not blocked' "$(jq -r '.plugins[0].update_blocked' <<<"$out")" null
eq 'upstream url' "$(jq -r '.plugins[0].upstream_url' <<<"$out")" "$B/upstream.git"
eq 'activity recorded' "$(jq -r '.activity.last_run.command' <<<"$out")" check
eq 'no run in progress' "$(jq -r '.activity.running' <<<"$out")" null

printf '\n== status --json, held and dirty ==\n'
commit_upstream 'printf "// NEEDS-JSON-HOLD\n" >> Widget.qml' 'hold for json'
STUB_FAIL_ON=NEEDS-JSON-HOLD "$GATE" check >/dev/null 2>&1
held=$(upstream_sha)
printf 'scratch\n' >"$idir/scratch.txt"
out=$("$GATE" status -p selftest.demo --json 2>/dev/null)
eq 'state held back' "$(jq -r '.plugins[0].state' <<<"$out")" 'held back'
eq 'next is approve' "$(jq -r '.plugins[0].next' <<<"$out")" approve
eq 'held sha' "$(jq -r '.plugins[0].held.sha' <<<"$out")" "$held"
eq 'upstream' "$(jq -r '.plugins[0].upstream' <<<"$out")" "$held"
eq 'latest review is the held one' "$(jq -r '.plugins[0].latest_review.sha' <<<"$out")" "$held"
eq 'latest review failed' "$(jq -r '.plugins[0].latest_review.verdict' <<<"$out")" 'REVIEW FAIL'
eq 'latest review subject' "$(jq -r '.plugins[0].latest_review.subject' <<<"$out")" 'hold for json'
eq 'dirty file listed' "$(jq -r '.plugins[0].dirty[0]' <<<"$out")" scratch.txt
eq 'held needs attention' "$(jq -c .attention <<<"$out")" '[{"name":"demo","why":"held"}]'
eq 'one commit pending' "$(jq -r '.plugins[0].pending' <<<"$out")" 1
eq 'held subject' "$(jq -r '.plugins[0].held.subject' <<<"$out")" 'hold for json'
eq 'held author' "$(jq -r '.plugins[0].held.author' <<<"$out")" 'gate test'
rm "$idir/scratch.txt"

printf '\n== reviews ==\n'
out=$("$GATE" reviews demo --json 2>/dev/null)
eq 'reviews --json exits 0' "$?" 0
eq 'reviews schema' "$(jq -r .schema <<<"$out")" 1
eq 'two reviews' "$(jq '.plugins[0].reviews | length' <<<"$out")" 2
eq 'newest first' "$(jq -r '.plugins[0].reviews[0].sha' <<<"$out")" "$held"
eq 'older one approved' "$(jq -r '.plugins[0].reviews[1].approval' <<<"$out")" reviewed
"$GATE" approve demo --reason 'json waiver' >/dev/null 2>&1
out=$("$GATE" reviews -p demo --json 2>/dev/null)
eq 'waived review' "$(jq -r '.plugins[0].reviews[0].approval' <<<"$out")" waived
out=$("$GATE" status --json 2>/dev/null)
eq 'waiver reason' "$(jq -r '.plugins[0].waiver.reason' <<<"$out")" 'json waiver'
eq 'ready to install' "$(jq -r '.plugins[0].next' <<<"$out")" update
eq 'ready needs attention' "$(jq -r '.attention[0].why' <<<"$out")" ready
printf 'scratch\n' >"$idir/scratch.txt"
out=$("$GATE" status --json 2>/dev/null)
eq 'dirty blocks update' "$(jq -r '.plugins[0].update_blocked' <<<"$out")" dirty
rm "$idir/scratch.txt"
out=$("$GATE" reviews demo 2>&1)
has <(printf '%s' "$out") 'approved by hand (waived)' 'reviews text names the waiver'
has <(printf '%s' "$out") 'hold for json' 'reviews text shows the subject'

printf '\n== failures are JSON too ==\n'
out=$("$GATE" status -p nope --json 2>"$B/status.err")
eq 'unknown plugin exits 1' "$?" 1
eq 'error code' "$(jq -r .code <<<"$out")" not_found
has <(jq -r .error <<<"$out") "no plugin named 'nope'" 'error message'
has "$B/status.err" "no plugin named 'nope'" 'message on stderr too'
out=$("$GATE" reviews nope --json 2>/dev/null)
eq 'reviews unknown plugin exits 1' "$?" 1
eq 'reviews error schema' "$(jq -r .schema <<<"$out")" 1
