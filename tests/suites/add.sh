# add: clone, review and install a new plugin; or hold it for approval.

make_upstream upstream

printf '\n== add ==\n'
"$GATE" add "$B/upstream.git" --dir added >/dev/null 2>&1
eq 'add exits 0' "$?" 0
has "$OMARCHY_LOG" 'plugin add' 'installed through omarchy'
has "$OMARCHY_LOG" 'plugin enable selftest.demo --section right' 'enabled in the default section'
assert 'tripwire installed in the new clone' test -x "$B/root/added/.git/hooks/post-merge"
has "$OMARCHY_LOG" "omarchy-git-url-check $B/upstream.git" 'URL checked by omarchy'

printf '\n== add refuses unsafe URLs before cloning ==\n'
for url in git://example.invalid/x http://example.invalid/x 'ext::sh -c x' -ux; do
  : >"$OMARCHY_LOG"
  out=$("$GATE" add --dir unsafe -- "$url" 2>&1)
  eq "$url: add fails" "$?" 1
  has <(printf '%s' "$out") "'$url'" "$url: refusal names the URL"
  refute "$url: nothing cloned" test -e "$B/root/unsafe"
  refute "$url: omarchy not asked" grep -q . "$OMARCHY_LOG"
done
out=$("$GATE" add git://example.invalid/x 2>&1)
has <(printf '%s' "$out") 'uses git://, which is not authenticated' 'git:// refusal explained'
: >"$OMARCHY_LOG"
out=$(STUB_URL_REFUSE=upstream "$GATE" add "$B/upstream.git" --dir unsafe 2>&1)
eq 'omarchy-git-url-check refusal: add fails' "$?" 1
has <(printf '%s' "$out") "omarchy-git-url-check refused '$B/upstream.git'" 'omarchy refusal explained'
refute 'omarchy-git-url-check refusal: nothing cloned' test -e "$B/root/unsafe"

printf '\n== doctor flags an unauthenticated origin ==\n'
git -C "$B/root/added" remote set-url origin git://example.invalid/upstream
out=$("$GATE" doctor -p added 2>&1)
has <(printf '%s' "$out") '✗ origin git://example.invalid/upstream uses git://' 'doctor reports git://'
git -C "$B/root/added" remote set-url origin "$B/upstream.git"

: >"$OMARCHY_LOG"
STUB_FAIL_ON='A fixture widget' "$GATE" add "$B/upstream.git" --dir rejected >/dev/null 2>&1
eq 'add fails closed' "$?" 1
eq 'nothing installed on FAIL' "$(grep -c 'plugin add' "$OMARCHY_LOG" || true)" 0
assert 'clone kept for inspection' test -d "$B/root/rejected"

printf '\n== add held, approved, installed by update ==\n'
make_upstream fresh selftest.fresh
fresh=$(git -C "$B/fresh" rev-parse HEAD)
fclone=$B/root/fresh
fidir=$B/cfg/omarchy/plugins/selftest.fresh

: >"$OMARCHY_LOG"
out=$(STUB_FAIL_ON='A fixture widget' "$GATE" add "$B/fresh.git" 2>&1)
eq 'fresh: add fails closed' "$?" 1
eq 'fresh: held records the reviewed commit' "$(head -1 "$B/state/fresh/held" 2>/dev/null)" "$fresh"
has <(printf '%s' "$out") 'omarchy-plugin-gate update -p fresh' 'fresh: add names the way forward'

"$GATE" approve fresh --reason 'read it myself' >/dev/null 2>&1
eq 'fresh: approve finds the held commit' "$(git -C "$fclone" rev-parse refs/heads/gate-approved)" "$fresh"

out=$("$GATE" status -p fresh 2>&1)
has <(printf '%s' "$out") 'update -p fresh' 'fresh: status names update -p'

out=$("$GATE" update 2>&1)
eq 'fresh: plain update does not install' "$(grep -c 'plugin add' "$OMARCHY_LOG" || true)" 0
has <(printf '%s' "$out") 'install with: omarchy-plugin-gate update -p fresh' 'fresh: plain update names update -p'

git -C "$fclone" -c commit.gpgsign=false commit -q --allow-empty -m 'local work'
"$GATE" update -p fresh >/dev/null 2>&1
eq 'fresh: refuses a clone off the approved commit' "$(grep -c 'plugin add' "$OMARCHY_LOG" || true)" 0
refute 'fresh: nothing installed off the approved commit' test -e "$fidir"
git -C "$fclone" reset -q --hard "$fresh"

"$GATE" update -p fresh >/dev/null 2>&1
eq 'fresh: update -p exits 0' "$?" 0
has "$OMARCHY_LOG" "plugin add $fclone --yes" 'fresh: installed through omarchy'
eq 'fresh: installed at the approved commit' "$(git -C "$fidir" rev-parse HEAD 2>/dev/null)" "$fresh"
has "$OMARCHY_LOG" 'plugin enable selftest.fresh --section right' 'fresh: enabled in the default section'
assert 'fresh: tripwire in the installed copy' test -x "$fidir/.git/hooks/post-merge"
out=$("$GATE" update -p fresh 2>&1)
has <(printf '%s' "$out") 'fresh: up to date' 'fresh: second update is a no-op'
