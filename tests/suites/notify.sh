# Desktop notifications for pending updates.

demo_approved
install_copy
export OMDALL_NOTIFY=all

printf '\n== notifications ==\n'
commit_upstream 'printf "// notify\n" >> Widget.qml' notify
"$GATE" check >/dev/null 2>&1
has "$NOTIFY_LOG" '-u normal -t 30000' 'normal urgency, 30s'
has "$NOTIFY_LOG" 'update ready' 'headline mentions the pending update'
eq 'notification id remembered' "$(cat "$B/state/notify.id" 2>/dev/null)" 4242
"$GATE" update >/dev/null 2>&1
eq 'id cleared after update' "$(cat "$B/state/notify.id" 2>/dev/null || echo none)" none
: >"$NOTIFY_LOG"
"$GATE" check >/dev/null 2>&1
eq 'quiet when nothing is pending' "$(wc -l <"$NOTIFY_LOG")" 0
commit_upstream 'printf "[Desktop Entry]\n" > notify.desktop' 'notify findings'
"$GATE" check >/dev/null 2>&1
has "$NOTIFY_LOG" 'cleared structural findings' 'notification flags cleared findings'
