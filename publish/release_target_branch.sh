#!/bin/bash
# The branch a release was cut from, printed on stdout.
#
# A release names the branch it targets, but a tag pushed by hand names a tag there,
# and a re-run of the workflow gets the same event it had the first time. So: the
# branch the release names when that is a branch, otherwise the branch that holds the
# commit the tag points at.
#
#   TARGET=$(bash release_target_branch.sh "$TARGET_COMMITISH" "$TAG")
#
# Prints an empty line when neither can be determined, which the caller has to treat
# as "the branch is unknown" rather than pushing to a branch called "".
set -uo pipefail

TARGET="${1:-}"
TAG="${2:-}"

if [ -n "$TARGET" ] && git ls-remote --exit-code --heads origin "$TARGET" > /dev/null 2>&1; then
    printf '%s\n' "$TARGET"
    exit 0
fi

if [ -n "$TAG" ]; then
    TAGGED=$(git rev-parse "$TAG^{commit}" 2>/dev/null || true)
    if [ -n "$TAGGED" ]; then
        # The branch whose tip is the tagged commit.
        BRANCH=$(git for-each-ref --format='%(refname:short) %(objectname)' refs/remotes/origin \
                 | sed 's|^origin/||' | grep -v '^HEAD ' \
                 | awk -v commit="$TAGGED" '$2 == commit { print $1 }' | head -1)
        if [ -n "$BRANCH" ]; then
            printf '%s\n' "$BRANCH"
            exit 0
        fi
        # Any branch that contains it, for a tag whose commit is not a tip.
        BRANCH=$(git branch -r --contains "$TAG" --format='%(refname:short)' \
                 | sed 's|^origin/||' | grep -v '^HEAD$' | head -1)
        if [ -n "$BRANCH" ]; then
            printf '%s\n' "$BRANCH"
            exit 0
        fi
    fi
fi

# What the release named, even when it looks like a tag: the caller reports it.
printf '%s\n' "$TARGET"
