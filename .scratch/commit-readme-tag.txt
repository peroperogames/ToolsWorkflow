fix: the README's git URL gets the tag, not the plain version

The `git#…` snippet names a ref a consumer has to resolve, and the published
version is not that ref: AccessKing publishes `0.3.0` to npm and tags the release
`0.3.0-base`. Writing `#v0.3.0` there would replace one broken link with another —
master's README says `#v0.2.5` today, and no such tag exists either.

So the two shapes take different values. `"com.prpr.accessking": "0.3.0"` is the
npm/OpenUPM version; `…git#0.3.0-base` is the tag, which the workflow passes as
`GIT_REF="$CI_COMMIT_TAG"` and which defaults to the version where a repository
tags with plain versions. The `v` the old snippet carried is dropped rather than
kept, because it is not part of this repository's tag names.

Checked locally against the real README:

    31:    "com.prpr.accessking": "https://github.com/peroperogames/AccessKing.git#0.3.0-base"
    50:    "com.prpr.accessking": "0.3.0"
    69:    "com.prpr.accessking": "0.3.0"

and a second run reports nothing to update.
