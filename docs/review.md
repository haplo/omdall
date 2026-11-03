# The review

Every candidate goes through two stages. Structural checks run first and need
no model. The model reviewer runs only if those checks pass. Anything
unexpected, like a crash, a timeout, missing output or an unreadable manifest,
gives `REVIEW FAIL`.

## Hard failures

These fail the review straight away. The model is never asked.

- **Too big:** the diff is larger than `max-patch` (2 MiB by default), too much
  for the reviewer to read in full.
- **Not readable as text:** the diff is not valid UTF-8, or a file git treats
  as binary is really code, so the reviewer would only see "Binary files
  differ". That covers code suffixes such as `.qml`, `.js`, `.sh`, `.py`,
  `.json` and `.desktop`, a `qmldir`, an entry point, and executables.
- **Native code:** an ELF file under any name, or a `.so`, `.node`, `.dll` or
  `.dylib`.
- **Checkout filters:** a `.gitattributes` that sets a `filter` (including Git
  LFS), a `.lfsconfig`, or a changed LFS pointer. A filter could write files
  that differ from the reviewed ones. omdall ignores the plugin's attributes in
  its own diffs, merges and resets.
- **Hidden targets:** symlinks, submodules and `.gitmodules`. The diff shows
  only where they point, not what is there.
- **Paths no plugin needs:** anything under `.git/` or `.ssh/`, files named
  `authorized_keys` or `sudoers`, and executables in any protected path (see
  findings below).
- **Manifest problems:** the `id` changed, isn't a valid plugin id, or the
  manifest can't be read. Also a manifest that fails
  `omarchy plugin validate`, or entry points that are missing or point outside
  the plugin. Without `omarchy` on `PATH` nothing can be validated, so every
  review fails.
- **Too many findings:** more than 40 in one candidate.

A valid plugin id uses letters, digits, `.`, `_` and `-`, starts with a letter
or digit, contains no `..`, and is not in the reserved `omarchy.*` namespace.

## Findings

Findings match patterns that are usually, but not always, a sign of trouble.
They are numbered `F1`, `F2`, …, printed before the review, and given to the
reviewer:

- binary files that aren't common images or fonts (PNG, JPEG, GIF, WebP, ICO,
  AVIF, BMP, WOFF, WOFF2, TTF)
- image or font files whose contents don't match their type
- protected paths some plugins use legitimately: `systemd/`, `omarchy/hooks`,
  `*.service`, `*.timer`, `*.socket`, `*.path`, `*.desktop`, `*.pem`, `*.key`,
  `*.p12`, and deleting any protected file
- new executables without a shebang
- changes to the manifest's `kinds` or `entryPoints`
- added lines that pipe a download or decoder into a shell, use `/dev/tcp`, or
  pipe into `sudo` or `pkexec`

The reviewer must clear every finding, one line each, after its verdict:

```
REVIEW PASS
F1 CLEARED systemd/ holds QML that displays unit status; nothing is installed
F2 CLEARED icon.bin is loaded by Icon.qml as image data
```

A pass becomes `REVIEW FAIL` if any finding is unanswered, answered twice,
answered `CONFIRMED`, or cleared without a reason, or if an answer refers to a
finding that doesn't exist. Passes that cleared findings are recorded in
`cleared`, and `check`, `status` and the notification point them out. These
are the approvals to double-check.

## The reviewer

The reviewer is an OpenCode agent, `omdall-reviewer`, that can only read, glob
and grep. It has no shell, can't write, and has no network access. It runs
inside the candidate's review directory, so the patch is all it can see. A
hostile `.opencode/` or `AGENTS.md` in the plugin is never loaded.

The prompt contains the findings, keyword hints, and the commit subjects,
authors and changed files. The plugin author controls that metadata, so it
goes in a block marked as untrusted, with control characters escaped and lines
cut to 200 characters.

The reviewer's first line must be exactly `REVIEW PASS` or `REVIEW FAIL`,
followed by its finding answers and reasons.

## Proof of reading

The patch given to the reviewer (`patch.review`) ends with a random code word.
The word is new for each run and never appears in the prompt. The reviewer
must end its answer with `SEEN <word>`. Without the right word the verdict is
`REVIEW FAIL`, because the reviewer did not read the whole patch. If the
attachment arrives cut off, the reviewer can page through `./patch.review` with
its read tool.
