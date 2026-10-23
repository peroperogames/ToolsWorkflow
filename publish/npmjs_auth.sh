#!/bin/bash
# The npmjs token, in a scratch .npmrc of its own.
#
# $HOME/.npmrc already holds the PeroNPM login on these runners, and writing the
# public registry's token into that same file would replace it — the next PeroNPM
# release would then fail with an auth error that points at the wrong registry.
# `npm publish --userconfig <this file>` reads this one instead, so one run can
# publish to both. Prints the path so the caller can pass it on.
#
#   NPMRC=$(bash npmjs_auth.sh) || exit 1
#   npm publish --userconfig "$NPMRC" --registry https://registry.npmjs.org/
set -uo pipefail

: "${NPMJS_TOKEN:?the npmjs channel needs the NPMJS_TOKEN secret}"

NPMRC="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/npmrc-npmjs"
# umask before the file exists, so the token is never briefly world readable.
umask 077
printf 'registry=https://registry.npmjs.org/\n//registry.npmjs.org/:_authToken=%s\n' "$NPMJS_TOKEN" > "$NPMRC"
echo "$NPMRC"
