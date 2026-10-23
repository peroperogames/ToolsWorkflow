#!/bin/bash
# Point a repository's README at the version being published.
#
# The publish workflow already bumps `package.json` and commits it back to the
# branch the release was cut from; a README that shows the version in its install
# snippet is the same fact written down twice, and it goes stale silently. This
# rewrites it in the same commit.
#
#   PACKAGE_NAME=com.prpr.accessking NEW_VERSION=0.3.0 bash update_readme_version.sh README.md
#
# Only lines that *name the package* are touched. On such a line the version next
# to the name is this package's version; on any other line a number like `2.5.5` is
# a dependency's, and rewriting it would be wrong. Two shapes are handled:
#
#   "com.prpr.accessking": "0.2.5"
#   "com.prpr.accessking": "https://github.com/peroperogames/AccessKing.git#v0.2.5"
#
# Anything else — a badge nobody can classify, a changelog heading — is left alone.
# A README with no version reference says so and exits 0: not every package writes
# its version down, and a publish must not fail because of it.
set -uo pipefail

README="${1:-README.md}"
PACKAGE_NAME="${PACKAGE_NAME:-}"
NEW_VERSION="${NEW_VERSION:-}"

if [ -z "$PACKAGE_NAME" ] || [ -z "$NEW_VERSION" ]; then
    echo "Error: PACKAGE_NAME and NEW_VERSION must be set" >&2
    exit 1
fi
if [ ! -f "$README" ]; then
    echo "No $README to update; nothing to do."
    exit 0
fi

escaped_pkg=$(printf '%s' "$PACKAGE_NAME" | sed 's/[.]/\\./g')
escaped_new=$(printf '%s' "$NEW_VERSION" | sed 's/[.&/]/\\&/g')
semver='[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?'

before=$(mktemp)
trap 'rm -f "$before"' EXIT
cp -f "$README" "$before"

sed -i -E \
    -e "/\"${escaped_pkg}\"/ {
        s/(\"${escaped_pkg}\"[[:space:]]*:[[:space:]]*\"[^\"]*#v?)${semver}\"/\1${escaped_new}\"/g
        s/(\"${escaped_pkg}\"[[:space:]]*:[[:space:]]*\")${semver}\"/\1${escaped_new}\"/g
    }" \
    "$README"

if cmp -s "$before" "$README"; then
    echo "Nothing to update in $README: it does not name $PACKAGE_NAME, or it already says $NEW_VERSION."
    exit 0
fi

echo "Updated $README:"
grep -n "\"${escaped_pkg}\"" "$README" | sed 's/^/  /'
