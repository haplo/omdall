# Desktop notifications for pending updates.

demo_approved
install_copy
export OMDALL_NOTIFY=all

printf '\n== notifications ==\n'
commit_upstream 'printf "// notify\n" >> Widget.qml' notify
"$GATE" check >/dev/null 2>&1
has "$NOTIFY_LOG" '-u normal -t 30000' 'normal urgency, 30s'
has "$NOTIFY_LOG" '-g 󰕥' 'the shield icon of the bar plugin'
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

printf '\n== a click opens status or the panel ==\n'
commit_upstream 'printf "// click\n" >> Widget.qml' click
: >"$NOTIFY_LOG"
"$GATE" check >/dev/null 2>&1
has "$NOTIFY_LOG" '--exec omarchy-launch-floating-terminal-with-presentation omdall status' \
  'terminal by default'
"$GATE" update >/dev/null 2>&1
commit_upstream 'printf "// panel\n" >> Widget.qml' panel
: >"$NOTIFY_LOG"
OMDALL_NOTIFY_ACTION=panel "$GATE" check >/dev/null 2>&1
has "$NOTIFY_LOG" '--exec omarchy-shell net.fidelramos.omdall open' 'panel on request'
mkdir -p "$B/cfg/omdall"
printf 'notify-action = "panel"\n' >"$B/cfg/omdall/config.toml"
"$GATE" update >/dev/null 2>&1
commit_upstream 'printf "// panel file\n" >> Widget.qml' 'panel file'
: >"$NOTIFY_LOG"
"$GATE" check >/dev/null 2>&1
has "$NOTIFY_LOG" '--exec omarchy-shell net.fidelramos.omdall open' 'panel from the config file'
: >"$NOTIFY_LOG"
"$GATE" update >/dev/null 2>&1
commit_upstream 'printf "// option\n" >> Widget.qml' option
"$GATE" check --notify-action terminal >/dev/null 2>&1
has "$NOTIFY_LOG" '--exec omarchy-launch-floating-terminal-with-presentation' 'the option wins'
rm "$B/cfg/omdall/config.toml"
