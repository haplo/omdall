# Approving a failed review

When a review fails, the commit is held back. If you read the change and decide
it is fine, `approve` lets that one commit through:

```sh
omdall approve my-plugin                     # show the evidence, ask why
omdall approve my-plugin --show              # print the diff first
omdall approve my-plugin --reason "checked"  # no prompt
omdall approve my-plugin --dry-run           # show what would happen
omdall update -p my-plugin
```

Without `--sha`, `approve` takes the held-back commit. It prints the verdict,
the structural findings and the patch path, then asks for a reason. The reason
can be empty. Use `--reason` when stdin is not a terminal. A commit that was
never reviewed needs `--show` or `--reason`.

`--show` prints the diff from the current `gate-approved` to the candidate,
which is exactly what the approval lets through. If this diff differs from the
one that was reviewed (because `gate-approved` has moved since, for example),
`approve` warns you.

Hard structural failures can be approved too, so read the printed failures
before you answer.

## What gets recorded

An approval covers one commit. It is not a standing trust setting. It is
written to `waived/<sha>` in the plugin's state directory, with:

- date, user and reason
- the base commit
- the blob hash of the approved patch (`patch-blob`), plus the hash of the
  reviewed patch if it was different (`evidence-blob`)

The failed verdict is kept, so `status` shows both `REVIEW FAIL` and
`approval waived by hand`.

`approve` moves `gate-approved` and installs the hooks. Run `update` to install
the commit. `approve` doesn't fetch, and `--sha` must name a commit reachable
from `origin/<branch>`.

## Control characters

Text from the plugin or the reviewer (the diff, the verdict, findings, held-back
reasons) is printed with control characters escaped. An escape sequence in a
hostile patch shows up as `\x1b…`, so it can't erase lines or write to your
clipboard. The stored `verdict`, `cleared` and `held` files are cleaned the
same way. `review.txt` keeps the reviewer's raw output.
