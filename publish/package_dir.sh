#!/bin/bash
# Which directory holds the package this release publishes.
#
# The caller may name it (`working-directory`), and most callers do — but the answer is
# in the repository: a UPM package is a directory whose package.json has a name, and the
# shallowest one is the package (a sample project nested deeper has a package.json too,
# and it is not the package). A wrong hint fails here, by name, instead of two steps
# later as a version that silently did not change.
#
#   bash package_dir.sh <repo root> [hint]
#
# Prints the directory relative to the repository root (`.` for the root itself), or
# exits non-zero with a reason when there is nothing to publish.
set -uo pipefail

ROOT="${1:-.}"
HINT="${2:-}"

if [ ! -d "$ROOT" ]; then
    echo "Error: '$ROOT' is not a directory" >&2
    exit 1
fi

has_package() { # dir
    [ -f "$1/package.json" ] && grep -q '"name"' "$1/package.json"
}

if [ -n "$HINT" ]; then
    if [ ! -d "$ROOT/$HINT" ]; then
        echo "Error: working-directory '$HINT' does not exist in the repository" >&2
        exit 1
    fi
    if ! has_package "$ROOT/$HINT"; then
        echo "Error: working-directory '$HINT' has no package.json with a name — this release has nothing to pack" >&2
        exit 1
    fi
    printf '%s\n' "$HINT"
    exit 0
fi

# The shallowest package.json with a name wins, then the first by path so the answer
# does not depend on the order the filesystem returns them in. Directories that only
# hold other packages are skipped, as are build outputs.
best=""
best_key=""
while IFS= read -r -d '' manifest; do
    grep -q '"name"' "$manifest" || continue
    dir=$(dirname "$manifest")
    rel=${dir#"$ROOT"}
    rel=${rel#/}
    [ -z "$rel" ] && rel="."
    slashes=${rel//[!\/]/}
    depth=${#slashes}
    key=$(printf '%03d|%s' "$depth" "$rel")
    if [ -z "$best_key" ] || [[ $key < $best_key ]]; then
        best_key=$key
        best=$rel
    fi
done < <(find "$ROOT" -name package.json -type f \
    -not -path '*/node_modules/*' \
    -not -path '*/.git/*' \
    -not -path '*/Library/*' \
    -not -path '*/obj/*' \
    -not -path '*/bin/*' \
    -not -path '*~/*' \
    -print0)

if [ -z "$best" ]; then
    echo "Error: no package.json with a name in the repository — nothing to publish" >&2
    exit 1
fi

printf '%s\n' "$best"
