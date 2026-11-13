#!/bin/bash
# Build the npm tarball of an AccessKing release the way the publish workflow does.
#
# The tarball in the run's artifact is what the manual first publish to npmjs takes;
# when that artifact is gone (a re-run deletes the previous attempt's), this rebuilds
# the same bytes from the released commit: folder rename, manifest rewrite, the
# repository's README copied in, then `npm pack`.
#
#   bash build_accessking_tarball.sh <checkout> <out dir> [tag]
set -uo pipefail

TOOLS=/e/Gatongone/GitClone/ToolsWorkflow
SRC="${1:?usage: build_accessking_tarball.sh <checkout> <out dir> [tag]}"
OUT="${2:?usage: build_accessking_tarball.sh <checkout> <out dir> [tag]}"
TAG="${3:-0.3.0-base}"

if [ ! -d "$SRC/Unity" ]; then
    echo "Error: $SRC does not look like an AccessKing checkout" >&2
    exit 1
fi
mkdir -p "$OUT"

echo "commit: $(git -C "$SRC" log -1 --format='%h %s')"

# 1. The packaging: a folder the manifest refers to with a `~` suffix is renamed so
#    Unity's convention (excluded from the import) is what the package ships.
CI_PROJECT_DIR="$SRC/Unity" bash "$TOOLS/publish/changefoldername.sh" > /dev/null

# 2. The manifest: name under the expected prefix, version from the tag.
( cd "$SRC/Unity" && CI_COMMIT_TAG="$TAG" EXPECTED_PACKAGE_PREFIX=com.prpr \
    bash "$TOOLS/publish/package_preprocess.sh" > /dev/null )

# 3. The README npm renders, which lives at the repository root.
if [ -f "$SRC/README.md" ] && [ ! -f "$SRC/Unity/README.md" ]; then
    cp "$SRC/README.md" "$SRC/Unity/README.md"
fi

# 4. Pack.
( cd "$SRC/Unity" && npm pack --pack-destination "$OUT" > /dev/null )

tarball=$(ls "$OUT"/*.tgz | head -1)
echo "tarball: $tarball"
echo "sha1:    $(sha1sum "$tarball" | cut -d' ' -f1)"
echo
echo "manifest:  $(tar --force-local -xOf "$tarball" package/package.json | tr -d '\n' | sed -n 's/.*"version": *"\([^"]*\)".*/\1/p')"
echo "readme:    $(tar --force-local -tzf "$tarball" | grep -c '^package/README.md$') file"
echo "samples:   $(tar --force-local -tzf "$tarball" | grep -c '^package/Samples~/') files under Samples~/"
echo "files:     $(tar --force-local -tzf "$tarball" | wc -l)"
echo
echo "the assembly inside:"
mkdir -p "$OUT/unpacked"
tar --force-local -xzf "$tarball" -C "$OUT/unpacked" package/Plugins/PeroTools2.AccessKing.Core.dll 2>/dev/null
if [ -f "$OUT/unpacked/package/Plugins/PeroTools2.AccessKing.Core.dll" ]; then
    ls -l "$OUT/unpacked/package/Plugins/PeroTools2.AccessKing.Core.dll" | awk '{print "  " $5 " bytes"}'
else
    echo "  not found in the tarball"
fi
