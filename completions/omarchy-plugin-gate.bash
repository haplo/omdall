# bash completion for omarchy-plugin-gate.
#
# scripts/install.sh links this file into $XDG_DATA_HOME/bash-completion/
# completions/omarchy-plugin-gate, where bash-completion looks for it on the
# first Tab. It uses plain bash builtins, so sourcing it from ~/.bashrc also
# works without bash-completion.
#
# Keep the commands and options in step with src/omarchy_plugin_gate/cli.py;
# tests/unit/test_completions.py fails when they drift apart.
#
# The helpers share `words`, `cword` and `settings` with _omarchy_plugin_gate,
# which declares them local.

# Interactive bash splits --opt=value into --opt, = and value, because = is in
# COMP_WORDBREAKS. Join them back so the rest sees the words argparse will.
_omarchy_plugin_gate_words() {
  local i word joining=0
  words=()
  cword=0
  for ((i = 0; i < ${#COMP_WORDS[@]}; i++)); do
    word=${COMP_WORDS[i]}
    if ((joining)); then
      words[-1]+=$word
      joining=0
    elif [[ $word == = && ${#words[@]} -gt 0 && ${words[-1]} == --* && ${words[-1]} != *=* ]]; then
      words[-1]+='='
      joining=1
    else
      words+=("$word")
    fi
    if ((i == COMP_CWORD)); then cword=$((${#words[@]} - 1)); fi
  done
}

# The --root and --state given on the line, so _complete looks where the command
# will. A leading ~ is expanded as the shell will expand it.
_omarchy_plugin_gate_settings() {
  local i word value
  settings=()
  for ((i = 1; i < cword; i++)); do
    word=${words[i]}
    case $word in
    --root | --state)
      ((i + 1 < cword)) || continue
      i=$((i + 1))
      value=${words[i]}
      ;;
    --root=* | --state=*)
      value=${word#*=}
      word=${word%%=*}
      ;;
    *) continue ;;
    esac
    [[ $value == "~" ]] && value=$HOME
    [[ $value == "~/"* ]] && value=$HOME/${value#"~/"}
    [[ -n $value ]] && settings+=("$word" "$value")
  done
}

_omarchy_plugin_gate_plugins() { # <prefix>
  local -a names
  local name
  mapfile -t names < <("${words[0]}" "${settings[@]}" _complete plugins 2>/dev/null)
  for name in "${names[@]}"; do
    [[ $name == "$1"* ]] && COMPREPLY+=("$name")
  done
}

_omarchy_plugin_gate_held() { # <prefix> <plugin>
  local -a shas
  local sha
  [[ -n $2 ]] || return 0
  mapfile -t shas < <("${words[0]}" "${settings[@]}" _complete held "$2" 2>/dev/null)
  for sha in "${shas[@]}"; do
    [[ $sha == "$1"* ]] && COMPREPLY+=("$sha")
  done
}

_omarchy_plugin_gate_dirs() { # <prefix>
  local dir
  compopt -o filenames 2>/dev/null
  while IFS= read -r dir; do
    COMPREPLY+=("$dir")
  done < <(compgen -d -- "$1")
}

# The plugin named on the line: -p NAME, --plugin NAME or --plugin=NAME, or the
# positional name after `approve` or `reviews`.
_omarchy_plugin_gate_plugin() {
  local i word
  for ((i = 1; i < cword; i++)); do
    word=${words[i]}
    case $word in
    -p | --plugin)
      if ((i + 1 < cword)); then printf '%s\n' "${words[i + 1]}"; fi
      return 0
      ;;
    --plugin=*)
      printf '%s\n' "${word#--plugin=}"
      return 0
      ;;
    esac
  done
  for ((i = 1; i < cword; i++)); do
    [[ ${words[i]} == approve || ${words[i]} == reviews ]] || continue
    for ((i = i + 1; i < cword; i++)); do
      word=${words[i]}
      case $word in
      -p | --plugin | --sha | --reason | --root | --state | --agent | --model | \
        --notify | --timeout | --max-patch) i=$((i + 1)) ;;
      -*) ;;
      *)
        printf '%s\n' "$word"
        return 0
        ;;
      esac
    done
  done
}

_omarchy_plugin_gate() {
  local cur prev cmd name flag i cword inline=0
  local -a words flags settings
  COMPREPLY=()
  _omarchy_plugin_gate_words
  cur=${words[cword]-}
  prev=
  ((cword > 0)) && prev=${words[cword - 1]}
  # --opt=value: complete the value; readline replaces only the part after =.
  if [[ $cur == --*=* ]]; then
    prev=${cur%%=*}
    cur=${cur#*=}
    inline=1
  fi

  cmd=
  for ((i = 1; i < cword; i++)); do
    case ${words[i]} in
    add | check | approve | update | status | reviews | doctor)
      cmd=${words[i]}
      break
      ;;
    esac
  done
  name=$(_omarchy_plugin_gate_plugin)
  _omarchy_plugin_gate_settings

  case $prev in
  -p | --plugin)
    _omarchy_plugin_gate_plugins "$cur"
    return 0
    ;;
  --sha)
    _omarchy_plugin_gate_held "$cur" "$name"
    return 0
    ;;
  --notify)
    COMPREPLY=($(compgen -W "all ready none" -- "$cur"))
    return 0
    ;;
  --root | --state)
    _omarchy_plugin_gate_dirs "$cur"
    return 0
    ;;
  --agent | --model | --timeout | --max-patch | --reason | --dir)
    return 0
    ;;
  esac
  ((inline)) && return 0

  flags=(-h --help --root --state --agent --model --notify --timeout --max-patch)
  case $cmd in
  add) flags+=(--dir --no-enable --no-wait) ;;
  approve) flags+=(-p --plugin --sha --reason --show -n --dry-run --no-wait) ;;
  check | update) flags+=(-p --plugin --no-wait) ;;
  status | reviews) flags+=(-p --plugin --json) ;;
  doctor) flags+=(-p --plugin --fix --no-wait) ;;
  esac
  [[ -n $cmd ]] || flags+=(--version)

  if [[ $cur == -* ]]; then
    for flag in "${flags[@]}"; do
      [[ $flag == "$cur"* ]] && COMPREPLY+=("$flag")
    done
    return 0
  fi

  if [[ -z $cmd ]]; then
    COMPREPLY=($(compgen -W "add check approve update status reviews doctor" -- "$cur"))
  elif [[ ($cmd == approve || $cmd == reviews) && -z $name ]]; then
    _omarchy_plugin_gate_plugins "$cur"
  fi
  return 0
}

complete -F _omarchy_plugin_gate omarchy-plugin-gate
