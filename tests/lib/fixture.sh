# The isolated environment and the repositories a suite starts from. Everything
# lives under $B, which the runner gives each suite.

setup_env() { # stubs first on PATH, private git config, state under $B
  export OMDALL_ROOT=$B/root
  export OMDALL_STATE=$B/state
  export XDG_CONFIG_HOME=$B/cfg
  export PATH=$B/bin:$PATH
  export GIT_CONFIG_GLOBAL=$B/gitconfig
  export GIT_CONFIG_NOSYSTEM=1
  export STUB_LOG=$B/stub.log
  export STUB_PROMPT=$B/stub.prompt
  export STUB_CWD=$B/stub.cwd
  export OMARCHY_LOG=$B/omarchy.log
  export NOTIFY_LOG=$B/notify.log
  export BUSCTL_LOG=$B/busctl.log
  export OMDALL_NOTIFY=none

  mkdir -p "$B"/{bin,root,state,cfg/omarchy/plugins}
  cp "$TESTS"/stubs/* "$B/bin/"
  chmod +x "$B"/bin/*

  git config --global user.name "gate test"
  git config --global user.email "gate@example.invalid"
  git config --global commit.gpgsign false
  git config --global tag.gpgsign false
  git config --global init.defaultBranch main
}

make_upstream() { # make_upstream <name> [<id>]: $B/<name> and bare $B/<name>.git from tests/plugin
  local dir=$B/$1
  mkdir -p "$dir"
  cp "$TESTS"/plugin/* "$dir/"
  if [[ -n ${2:-} ]]; then
    jq --arg id "$2" '.id = $id' "$TESTS/plugin/manifest.json" >"$dir/manifest.json"
  fi
  git -C "$dir" init -q
  git -C "$dir" add -A
  git -C "$dir" commit -qm "initial import"
  git init -q --bare "$dir.git"
  git -C "$dir" push -q "$dir.git" HEAD:main
  git -C "$dir.git" symbolic-ref HEAD refs/heads/main
}

demo_clone() { # the demo upstream and its gate clone, not yet reviewed
  make_upstream upstream
  git clone -q "$B/upstream.git" "$B/root/demo"
}

demo_approved() { # demo_clone with the initial import reviewed and approved
  demo_clone
  "$GATE" check >/dev/null 2>&1 || no 'fixture: initial review passes'
}

install_copy() { # the installed copy, at the approved commit and tracking the clone
  idir=$B/cfg/omarchy/plugins/selftest.demo
  git clone -q "$B/root/demo" "$idir"
  git -C "$idir" remote set-url origin "$B/root/demo"
  git -C "$idir" reset -q --hard "$(ap)"
}
