# Where the gate looks for clones when nothing says otherwise.

printf '\n== default root ==\n'
out=$(env -u OMDALL_ROOT HOME="$B/home" "$GATE" check 2>&1)
eq 'root defaults to ~/Work/omarchy-plugins' "$out" "No plugins under $B/home/Work/omarchy-plugins."
