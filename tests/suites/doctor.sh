# doctor compares the installed reviewer agent with the template.

demo_approved

printf '\n== doctor checks the reviewer agent ==\n'
agent=$B/cfg/opencode/agents/omdall-reviewer.md
mkdir -p "$(dirname "$agent")"
cp "$REPO/agents/omdall-reviewer.md.in" "$agent"
out=$("$GATE" doctor 2>&1)
has <(printf '%s' "$out") "reviewer agent: $agent" 'current agent accepted'
printf 'stale\n' >>"$agent"
out=$("$GATE" doctor 2>&1)
has <(printf '%s' "$out") 'reviewer agent is out of date' 'stale agent reported'
