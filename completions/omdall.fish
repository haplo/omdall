# fish completion for omdall.
#
# scripts/install.sh links this file into
# $XDG_DATA_HOME/fish/vendor_completions.d/omdall.fish, which is
# on fish's $fish_complete_path.
#
# Keep the commands and options in step with src/omdall/cli.py;
# tests/unit/test_completions.py fails when they drift apart.

function __omdall_no_command
    not __fish_seen_subcommand_from add adopt check approve update status reviews doctor
end

# The --root and --state given on the line, so _complete looks where the command
# will. A leading ~ is expanded as the shell will expand it.
function __omdall_settings
    set -l tokens (commandline -opc)
    set -l i 2
    while test $i -le (count $tokens)
        set -l token $tokens[$i]
        set -l value ''
        switch $token
            case --root --state
                set i (math $i + 1)
                test $i -le (count $tokens); or break
                set value $tokens[$i]
            case '--root=*' '--state=*'
                set value (string replace -r -- '^[^=]*=' '' $token)
                set token (string replace -r -- '=.*' '' $token)
        end
        if test -n "$value"
            printf '%s\n' $token (string replace -r -- '^~(?=/|$)' $HOME $value)
        end
        set i (math $i + 1)
    end
end

function __omdall_plugins
    command omdall (__omdall_settings) _complete plugins 2>/dev/null
end

function __omdall_unguarded
    command omdall (__omdall_settings) _complete unguarded 2>/dev/null
end

function __omdall_needs_unguarded
    __fish_seen_subcommand_from adopt; and test -z "$(__omdall_plugin)"
end

function __omdall_needs_plugin
    __fish_seen_subcommand_from approve reviews; and test -z "$(__omdall_plugin)"
end

# The plugin named on the line, from -p/--plugin or, after approve, reviews or
# adopt, the positional name or id.
function __omdall_plugin
    set -l tokens (commandline -opc)
    for i in (seq (count $tokens) -1 2)
        switch $tokens[$i]
            case -p --plugin
                if test (math $i + 1) -le (count $tokens)
                    echo $tokens[(math $i + 1)]
                end
                return
            case '--plugin=*'
                string replace -- '--plugin=' '' $tokens[$i]
                return
        end
    end
    set -l i (contains -i -- approve $tokens)
    test -n "$i"; or set i (contains -i -- reviews $tokens)
    test -n "$i"; or set i (contains -i -- adopt $tokens)
    test -n "$i"; or return
    set -l j (math $i + 1)
    while test $j -le (count $tokens)
        set -l token $tokens[$j]
        if contains -- $token -p --plugin --sha --reason --url --dir --root --state \
                --agent --model --notify --notify-action --timeout --max-patch
            set j (math $j + 2)
            continue
        end
        if not string match -q -- '-*' $token
            echo $token
            return
        end
        set j (math $j + 1)
    end
end

function __omdall_shas
    set -l plugin (__omdall_plugin)
    test -n "$plugin"; or return
    command omdall (__omdall_settings) _complete held "$plugin" 2>/dev/null
end

complete -c omdall -f
complete -c omdall -s h -l help -d 'Show usage'
complete -c omdall -n '__omdall_no_command' -l version -d 'Show the version'
complete -c omdall -l root -r -a '(__fish_complete_directories)' -d 'Gate root'
complete -c omdall -l state -r -a '(__fish_complete_directories)' -d 'Evidence and markers'
complete -c omdall -l agent -x -d 'Reviewer agent'
complete -c omdall -l model -x -d 'Reviewer model'
complete -c omdall -l notify -x -a 'all ready none' -d 'Notification policy'
complete -c omdall -l notify-action -x -a 'terminal panel' -d 'What a notification click opens'
complete -c omdall -l timeout -x -d 'Reviewer timeout in seconds'
complete -c omdall -l max-patch -x -d 'Largest diff to review, in bytes'

complete -c omdall -n '__omdall_no_command' -a add -d 'Clone a plugin, review it, install it disabled'
complete -c omdall -n '__omdall_no_command' -a adopt -d 'Bring an installed plugin under the gate'
complete -c omdall -n '__omdall_no_command' -a check -d 'Review upstream changes'
complete -c omdall -n '__omdall_no_command' -a approve -d 'Approve a held candidate by hand'
complete -c omdall -n '__omdall_no_command' -a update -d 'Install approved commits'
complete -c omdall -n '__omdall_no_command' -a status -d 'Show installed, approved and held state'
complete -c omdall -n '__omdall_no_command' -a reviews -d 'List the recorded reviews'
complete -c omdall -n '__omdall_no_command' -a doctor -d 'Verify the wiring'

complete -c omdall -n '__fish_seen_subcommand_from add adopt' -l dir -x -d 'Clone directory name'
complete -c omdall -n '__fish_seen_subcommand_from adopt' -l url -x -d 'Upstream repository'
complete -c omdall -n '__omdall_needs_unguarded' -a '(__omdall_unguarded)' -d 'Installed plugin'
complete -c omdall -n '__fish_seen_subcommand_from add' -l no-enable -d 'Do not enable on REVIEW PASS'
complete -c omdall -n '__fish_seen_subcommand_from add adopt approve check update doctor' -l no-wait -d 'Exit 75 instead of waiting for another run'

complete -c omdall -n '__fish_seen_subcommand_from approve' -s p -l plugin -x -a '(__omdall_plugins)' -d 'Plugin'
complete -c omdall -n '__fish_seen_subcommand_from approve' -l sha -x -a '(__omdall_shas)' -d 'Held commit'
complete -c omdall -n '__fish_seen_subcommand_from approve' -l reason -x -d 'Reason for the waiver'
complete -c omdall -n '__fish_seen_subcommand_from approve' -l show -d 'Print the patch before asking'
complete -c omdall -n '__fish_seen_subcommand_from approve' -s n -l dry-run -d 'Show the decision, change nothing'
complete -c omdall -n '__omdall_needs_plugin' -a '(__omdall_plugins)' -d 'Plugin'

complete -c omdall -n '__fish_seen_subcommand_from check update status reviews' -s p -l plugin -x -a '(__omdall_plugins)' -d 'Plugin'
complete -c omdall -n '__fish_seen_subcommand_from add adopt check update status reviews doctor' -l json -d 'Print JSON'
complete -c omdall -n '__fish_seen_subcommand_from doctor' -s p -l plugin -x -a '(__omdall_plugins)' -d 'Plugin'
complete -c omdall -n '__fish_seen_subcommand_from doctor' -l fix -d 'Install missing hooks'
