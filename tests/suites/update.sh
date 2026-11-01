# update moves the installed copy, but only to a reviewed or waived commit, and
# only when nothing on disk differs from the installed commit.

demo_approved
install_copy

printf '\n== update ==\n'
commit_upstream 'printf "// second\n" >> Widget.qml' second
"$GATE" check >/dev/null 2>&1
before=$(git -C "$idir" rev-parse HEAD)
"$GATE" update >/dev/null 2>&1
eq 'installed copy moved to approved' "$(git -C "$idir" rev-parse HEAD)" "$(ap)"
refute 'it actually moved' test "$before" = "$(ap)"

printf '\n== update refuses an unreviewed commit ==\n'
commit_upstream 'printf "// third\n" >> Widget.qml' third
"$GATE" check >/dev/null 2>&1
rm -f "$B/state/demo/reviewed/$(ap)"
snapshot=$(git -C "$idir" rev-parse HEAD)
out=$("$GATE" update 2>&1)
eq 'installed copy untouched' "$(git -C "$idir" rev-parse HEAD)" "$snapshot"
has <(printf '%s' "$out") 'no review or waiver record' 'refusal explained'

printf '\n== update refuses an installed copy with local changes ==\n'
commit_upstream 'printf "// fourth\n" >> Widget.qml' fourth
"$GATE" check >/dev/null 2>&1
snapshot=$(git -C "$idir" rev-parse HEAD)
printf '// local edit\n' >>"$idir/Widget.qml"
out=$("$GATE" update 2>&1)
eq 'edited copy untouched' "$(git -C "$idir" rev-parse HEAD)" "$snapshot"
has <(printf '%s' "$out") 'the installed copy has local changes (Widget.qml); not updating' \
  'edit refusal explained'
has <(printf '%s' "$("$GATE" status 2>&1)") 'modified: Widget.qml' 'status shows the edit'
has <(printf '%s' "$("$GATE" doctor 2>&1)") 'installed copy has local changes: Widget.qml' \
  'doctor reports the edit'
git -C "$idir" checkout -q -- Widget.qml
printf 'x\n' >"$idir/extra.qml"
out=$("$GATE" update 2>&1)
eq 'copy with an untracked file untouched' "$(git -C "$idir" rev-parse HEAD)" "$snapshot"
has <(printf '%s' "$out") 'local changes (extra.qml)' 'untracked file refusal explained'
rm "$idir/extra.qml"

printf '\n== ignored files are reported, not refused ==\n'
mkdir -p "$idir/.git/info" "$idir/cache"
printf 'cache/\n' >>"$idir/.git/info/exclude"
printf 'x\n' >"$idir/cache/x"
has <(printf '%s' "$("$GATE" doctor 2>&1)") 'ignored files (not reviewed): cache/x' \
  'doctor mentions ignored files'
refute 'ignored files are not a problem' grep -q '✗ installed copy has local changes' \
  <(printf '%s' "$("$GATE" doctor 2>&1)")
"$GATE" update >/dev/null 2>&1
eq 'ignored files do not block update' "$(git -C "$idir" rev-parse HEAD)" "$(ap)"

printf '\n== an installed commit that was never reviewed is reported ==\n'
out=$("$GATE" status 2>&1)
refute 'reviewed commit not flagged' grep -q 'never reviewed' <(printf '%s' "$out")
git -C "$idir" commit -q --allow-empty -m 'local commit'
has <(printf '%s' "$("$GATE" status 2>&1)") 'installed commit never reviewed' \
  'status flags the unreviewed commit'
has <(printf '%s' "$("$GATE" doctor 2>&1)") "installed commit $(git -C "$idir" rev-parse HEAD) was never reviewed" \
  'doctor flags the unreviewed commit'
