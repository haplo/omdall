# adopt: bring plugins installed with plain `omarchy plugin add` under the gate,
# and list the ones that are not, in status --json.

plugins=$B/cfg/omarchy/plugins

omarchy_install() { # omarchy_install <upstream> <id> <origin>: as omarchy plugin add would
  git clone -q "$B/$1.git" "$plugins/$2"
  git -C "$plugins/$2" remote set-url origin "$3"
}
unguarded() { "$GATE" status --json 2>/dev/null | jq -r ".unguarded[] | select(.id == \"$1\") | $2"; }
origin_of() { git -C "$plugins/$1" remote get-url origin 2>/dev/null; }

# Network URLs that git quietly rewrites to the local fixtures.
for name in weather old other; do
  make_upstream "$name" "selftest.$name"
  git config --global "url.$B/$name.git.insteadOf" "https://example.invalid/acme/$name"
done
make_upstream held selftest.held
git config --global "url.$B/held.git.insteadOf" "https://example.invalid/acme/held"

printf '\n== unguarded plugins are listed ==\n'
omarchy_install weather selftest.weather https://example.invalid/acme/weather
omarchy_install old selftest.old https://example.invalid/acme/old
omarchy_install held selftest.held https://example.invalid/acme/held
mkdir -p "$plugins/selftest.hand"
cp "$TESTS"/plugin/* "$plugins/selftest.hand/"
jq '.id = "selftest.hand"' "$TESTS/plugin/manifest.json" >"$plugins/selftest.hand/manifest.json"
omarchy_install other selftest.local "$B/other.git"
jq '.id = "selftest.local"' "$TESTS/plugin/manifest.json" >"$plugins/selftest.local/manifest.json"
git -C "$plugins/selftest.local" -c commit.gpgsign=false commit -qam 'local id'
omarchy_install other selftest.plain http://example.invalid/acme/other
jq '.id = "selftest.plain"' "$TESTS/plugin/manifest.json" >"$plugins/selftest.plain/manifest.json"
mkdir -p "$plugins/omarchy.core"
printf '{"id": "omarchy.core"}\n' >"$plugins/omarchy.core/manifest.json"
ln -s "$plugins/selftest.weather" "$plugins/selftest.link"

eq 'adoptable' "$(unguarded selftest.weather .adoptable)" true
eq 'name' "$(unguarded selftest.weather .name)" 'Selftest Demo'
eq 'origin' "$(unguarded selftest.weather .origin)" https://example.invalid/acme/weather
eq 'git' "$(unguarded selftest.weather .git)" true
eq 'head' "$(unguarded selftest.weather .head)" "$(git -C "$plugins/selftest.weather" rev-parse HEAD)"
eq 'clean' "$(unguarded selftest.weather .dirty)" false
eq 'hand-installed' "$(unguarded selftest.hand .reason)" no_git
eq 'local origin' "$(unguarded selftest.local .reason)" local_origin
eq 'insecure origin' "$(unguarded selftest.plain .reason)" insecure_url
eq 'omarchy ids are not listed' "$(unguarded omarchy.core .id)" ''
eq 'symbolic links are not followed' "$(unguarded selftest.link .id)" ''
eq 'not part of attention' "$("$GATE" status --json 2>/dev/null | jq -c .attention)" '[]'

printf '\n== adopt from origin ==\n'
head=$(git -C "$plugins/selftest.weather" rev-parse HEAD)
: >"$OMARCHY_LOG"
"$GATE" adopt selftest.weather --json >"$B/out" 2>"$B/err"
eq 'adopt exits 0' "$?" 0
eq 'outcome' "$(jq -r '.results[0].outcome' "$B/out")" adopted
eq 'review outcome' "$(jq -r '.results[0].review' "$B/out")" approved
eq 'clone name' "$(jq -r '.results[0].name' "$B/out")" weather
eq 'installed copy fetches from the clone' "$(origin_of selftest.weather)" "$B/root/weather"
eq 'installed head did not move' "$(git -C "$plugins/selftest.weather" rev-parse HEAD)" "$head"
eq 'approved' "$(git -C "$B/root/weather" rev-parse refs/heads/gate-approved)" "$head"
has "$B/state/weather/adopted" 'previous-origin: https://example.invalid/acme/weather' \
  'previous origin recorded'
has "$B/state/weather/adopted" "installed-head: $head" 'installed head recorded'
assert 'tripwire in the clone' test -x "$B/root/weather/.git/hooks/post-merge"
assert 'tripwire in the installed copy' test -x "$plugins/selftest.weather/.git/hooks/post-merge"
refute 'never disabled' grep -q 'plugin disable' "$OMARCHY_LOG"
eq 'no longer unguarded' "$(unguarded selftest.weather .id)" ''
eq 'last check' "$(jq -r .last_check.summary "$B/state/activity.json")" \
  "$(jq -r .summary "$B/out")"
out=$("$GATE" doctor -p weather 2>&1)
has <(printf '%s' "$out") 'installed copy tracks the gate clone' 'doctor is happy'

printf '\n== adopting never moves the installed copy ==\n'
old_head=$(git -C "$plugins/selftest.old" rev-parse HEAD)
(cd "$B/old" && printf '// newer\n' >>Widget.qml && git add -A &&
  git -c commit.gpgsign=false commit -qm newer && git push -q "$B/old.git" HEAD:main)
"$GATE" adopt selftest.old >"$B/out" 2>&1
eq 'adopt exits 0' "$?" 0
eq 'installed head kept' "$(git -C "$plugins/selftest.old" rev-parse HEAD)" "$old_head"
has "$B/out" 'was never reviewed' 'adopt names the unreviewed installed commit'
eq 'never reviewed until update' \
  "$("$GATE" status --json 2>/dev/null | jq -r '.attention[] | select(.name == "old") | .why')" \
  never_reviewed

printf '\n== a failed review leaves the plugin enabled ==\n'
: >"$OMARCHY_LOG"
STUB_FAIL_ON='A fixture widget' "$GATE" adopt selftest.held --json >"$B/out" 2>/dev/null
eq 'held adopt exits 1' "$?" 1
eq 'still adopted' "$(jq -r '.results[0].outcome' "$B/out")" adopted
eq 'review held' "$(jq -r '.results[0].review' "$B/out")" held
eq 'points at the clone' "$(origin_of selftest.held)" "$B/root/held"
refute 'not disabled' grep -q 'plugin disable' "$OMARCHY_LOG"
eq 'held needs attention' \
  "$("$GATE" status --json 2>/dev/null | jq -r '.attention[] | select(.name == "held") | .why')" held

printf '\n== refusals ==\n'
"$GATE" adopt selftest.weather --json >"$B/out" 2>/dev/null
eq 'already guarded' "$(jq -r .code "$B/out")" already_guarded
"$GATE" adopt selftest.missing --json >"$B/out" 2>/dev/null
eq 'not installed' "$(jq -r .code "$B/out")" not_installed
"$GATE" adopt omarchy.core --json >"$B/out" 2>/dev/null
eq 'omarchy id refused' "$?" 1
has <(jq -r .error "$B/out") 'not a plugin id omdall can adopt' 'omarchy id refusal explained'
"$GATE" adopt selftest.plain --json >"$B/out" 2>/dev/null
eq 'insecure origin refused' "$(jq -r .code "$B/out")" refused_url
eq 'insecure origin kept' "$(origin_of selftest.plain)" http://example.invalid/acme/other
refute 'nothing cloned for an insecure origin' test -e "$B/root/other"
"$GATE" adopt selftest.local --json >"$B/out" 2>/dev/null
eq 'local origin refused' "$(jq -r .code "$B/out")" refused_url
"$GATE" adopt selftest.local --url https://example.invalid/acme/other --json >"$B/out" 2>/dev/null
eq 'id mismatch' "$(jq -r .code "$B/out")" id_mismatch
refute 'mismatched clone removed' test -e "$B/root/other"
eq 'origin untouched after a mismatch' "$(origin_of selftest.local)" "$B/other.git"
"$GATE" adopt selftest.local --url https://example.invalid/acme/weather --json >"$B/out" 2>/dev/null
eq 'name taken' "$(jq -r .code "$B/out")" name_taken

printf '\n== an error while adopting puts the origin back ==\n'
jq '.id = "selftest.local"' "$TESTS/plugin/manifest.json" >"$B/other/manifest.json"
(cd "$B/other" && git add -A && git -c commit.gpgsign=false commit -qm 'local id' &&
  git push -q "$B/other.git" HEAD:main)
mkdir -p "$B/state"
printf 'not a directory\n' >"$B/state/other"
"$GATE" adopt selftest.local --url https://example.invalid/acme/other >/dev/null 2>&1
eq 'adopt fails' "$?" 1
eq 'origin restored' "$(origin_of selftest.local)" "$B/other.git"
refute 'fresh clone removed' test -e "$B/root/other"
rm "$B/state/other"

printf '\n== adopt with --url ==\n'
local_head=$(git -C "$plugins/selftest.local" rev-parse HEAD)
"$GATE" adopt selftest.local --url https://example.invalid/acme/other --dir local-copy >/dev/null 2>&1
eq 'adopt --url exits 0' "$?" 0
eq 'clone named by --dir' "$(origin_of selftest.local)" "$B/root/local-copy"
eq 'clone origin is the given url' "$(git -C "$B/root/local-copy" config --get remote.origin.url)" \
  https://example.invalid/acme/other
eq 'installed head kept' "$(git -C "$plugins/selftest.local" rev-parse HEAD)" "$local_head"
has "$B/state/local-copy/adopted" "previous-origin: $B/other.git" 'previous origin recorded'

printf '\n== a hand-installed copy becomes a checkout, files untouched ==\n'
git config --global "url.$B/handup.git.insteadOf" https://example.invalid/acme/hand
make_upstream handup selftest.hand
before=$(cd "$plugins/selftest.hand" && sha256sum ./* | sort)
"$GATE" adopt selftest.hand --json >"$B/out" 2>/dev/null
eq 'no origin to adopt from' "$(jq -r .code "$B/out")" refused_url
"$GATE" adopt selftest.hand --url https://example.invalid/acme/hand >/dev/null 2>&1
eq 'hand install adopted' "$?" 0
eq 'files untouched' "$(cd "$plugins/selftest.hand" && sha256sum ./* | sort)" "$before"
eq 'installed at the clone commit' "$(git -C "$plugins/selftest.hand" rev-parse HEAD)" \
  "$(git -C "$B/root/hand" rev-parse refs/heads/gate-approved)"
eq 'no local changes' "$(git -C "$plugins/selftest.hand" status --porcelain)" ''
