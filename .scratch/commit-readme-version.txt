feat: the publish bumps the README's version too

The install snippet in a README is the same fact as `package.json`, written down
twice, and it goes stale silently: AccessKing's master README says

    "com.prpr.accessking": "0.2.5"
    "com.prpr.accessking": "https://github.com/peroperogames/AccessKing.git#v0.2.5"

while `package.json` on the branch is already past that, because only `package.json`
was ever bumped and committed back.

`publish/update_readme_version.sh` rewrites those references to the version being
published, and the publish workflow runs it right after `package_preprocess.sh`, in
the same "Commit version update" commit as the `package.json` bump — one commit that
says the version changed, not two.

Only lines that *name the package* are touched. On such a line the version next to
the name is this package's version; on any other line a number like `2.5.5` is a
dependency's. Two shapes are handled — `"<pkg>": "0.2.5"` and
`"<pkg>": "…git#v0.2.5"` — and anything else is left alone. The script is idempotent,
says what it changed, and exits 0 when the README is absent or already correct: not
every package writes its version down, and a publish must not fail over a README.

Checked locally against AccessKing's real README (631 lines, fetched from master):
three lines change and nothing else —

      31:    "com.prpr.accessking": "https://github.com/peroperogames/AccessKing.git#v0.3.0"
      50:    "com.prpr.accessking": "0.3.0"
      69:    "com.prpr.accessking": "0.3.0"

`com.cysharp.unitask: 2.5.5` on line 16 is untouched, a second run says nothing to
update, a README that never names the package is untouched, and a missing README is a
no-op with a green exit.
