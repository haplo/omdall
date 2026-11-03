# The review of one candidate: bootstrap, evidence, passing and failing updates.

demo_clone

printf '\n== bootstrap ==\n'
"$GATE" check >/dev/null 2>&1
eq 'check exits 0' "$?" 0
eq 'gate-approved == HEAD' "$(ap)" "$(git -C "$B/root/demo" rev-parse HEAD)"
eq 'one reviewer call' "$(invocations)" 1
eq 'verdict PASS' "$(last_verdict)" "REVIEW PASS"
eq 'structural log PASS' "$(cat "$(vdir)mech.txt")" 'PASS structural pre-checks'
refute 'no structural findings' test -s "$(vdir)findings.txt"
has "$STUB_PROMPT" 'Structural findings: none.' 'prompt says there are no findings'
eq 'marker written' "$(ls "$B/state/demo/reviewed" | head -1)" "$(ap)"
eq 'reviewer runs from the review directory' "$(cat "$STUB_CWD")/" "$(vdir)"
assert 'reviewed copy ends with the code word' \
  grep -q '^omdall: end of patch, code word [0-9a-f]\{16\}$' <(tail -n 1 "$(vdir)patch.review")
refute 'raw patch left untouched' grep -q 'code word' "$(vdir)patch"
refute 'code word not in the prompt' grep -q 'code word [0-9a-f]\{16\}' "$STUB_PROMPT"

printf '\n== no-op ==\n'
n0=$(invocations)
"$GATE" check >/dev/null 2>&1
eq 'no extra reviewer call' "$(invocations)" "$n0"

printf '\n== clean update ==\n'
commit_upstream 'printf "// tidy\n" >> Widget.qml' tidy
n0=$(invocations)
"$GATE" check >/dev/null 2>&1
n1=$(invocations)
eq 'reviewer consulted' "$((n1 - n0))" 1
eq 'approved advanced' "$(ap)" "$(upstream_sha)"
eq 'clone main fast-forwarded' "$(git -C "$B/root/demo" rev-parse HEAD)" "$(ap)"
eq 'verdict PASS' "$(last_verdict)" "REVIEW PASS"

printf '\n== hints are advisory ==\n'
base=$(ap)
reset_upstream "$base"
commit_upstream 'printf "// subprocess api_key token\n" >> Widget.qml' hints
"$GATE" check >/dev/null 2>&1
eq 'approved advanced' "$(ap)" "$(upstream_sha)"
has "$(vdir)hints.txt" subprocess 'hint collected'

printf '\n== default patch limit ==\n'
base=$(ap)
reset_upstream "$base"
commit_upstream 'head -c 1000000 /dev/zero | tr "\0" "a" | fold -w 100 > big.txt' 'large patch'
n0=$(invocations)
"$GATE" check >/dev/null 2>&1
eq 'a 1 MB patch is reviewed' "$(($(invocations) - n0))" 1
eq 'a 1 MB patch can pass' "$(ap)" "$(upstream_sha)"

printf '\n== reviewer outcomes ==\n'
base=$(ap)
reset_upstream "$base"
commit_upstream 'printf "// NEEDS-HUMAN\n" >> Widget.qml' suspicious
n0=$(invocations)
STUB_FAIL_ON=NEEDS-HUMAN "$GATE" check >/dev/null 2>&1
n1=$(invocations)
eq 'reviewer consulted' "$((n1 - n0))" 1
eq 'FAIL does not advance' "$(ap)" "$base"
eq 'verdict FAIL' "$(last_verdict)" "REVIEW FAIL"
has "$(vdir)verdict" 'stub reviewer disliked' 'reason kept'
eq 'held file names the commit' "$(head -1 "$B/state/demo/held")" "$(upstream_sha)"
reset_upstream "$base"

commit_upstream 'printf "// harmless\n" >> Widget.qml' crash
STUB_RC=1 "$GATE" check >/dev/null 2>&1
eq 'crash does not advance' "$(ap)" "$base"
has "$(vdir)verdict" 'Reviewer run failed' 'crash fails closed'
