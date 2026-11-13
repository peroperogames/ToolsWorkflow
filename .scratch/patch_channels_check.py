"""One-off: a prerelease tag downgrades the channels to PeroNPM, and the checks say so."""

from pathlib import Path

root = Path(__file__).resolve().parent.parent
resolver = root / "publish" / "resolve_channels.sh"
check = root / ".scratch" / "check_channels.sh"

text = resolver.read_text(encoding="utf-8")
old = '''TRIGGER_TAG="${GITHUB_REF_NAME:-${TAG:-${CI_COMMIT_TAG:-}}}"
source "$(dirname "${BASH_SOURCE[0]}")/version_from_tag.sh"
VERSION=$(extract_version "$TRIGGER_TAG") || exit 1
if ! is_release_tag "$TRIGGER_TAG"; then
    if [ "$CHANNELS" != "peronpm" ]; then
        echo "tag '$TRIGGER_TAG' is a prerelease version ($VERSION): publishing to PeroNPM only, whatever else was asked for."
    fi
    CHANNELS="peronpm"
fi
'''
new = '''TRIGGER_TAG="${GITHUB_REF_NAME:-${TAG:-${CI_COMMIT_TAG:-}}}"
source "$(dirname "${BASH_SOURCE[0]}")/version_from_tag.sh"
if [ -n "$TRIGGER_TAG" ]; then
    VERSION=$(extract_version "$TRIGGER_TAG") || exit 1
    if ! is_release_tag "$TRIGGER_TAG"; then
        echo "tag '$TRIGGER_TAG' is a prerelease version ($VERSION): publishing to PeroNPM only, whatever else was asked for."
        CHANNELS="peronpm"
    fi
else
    echo "No release tag in the environment; publishing to the channels as asked."
fi
'''
assert text.count(old) == 1
resolver.write_text(text.replace(old, new), encoding="utf-8", newline="\n")

text = check.read_text(encoding="utf-8")
old = '''# Each case is a private environment, so nothing leaks between them.
resolve() { # env assignments..., then runs the resolver
  env "$@" bash "$RESOLVE" 2>&1
}
'''
new = '''# Each case is a private environment, so nothing leaks between them. A release tag is
# the default: a version with no suffix is what publishes to every channel.
resolve() { # env assignments..., then runs the resolver
  env GITHUB_REF_NAME=0.3.0 "$@" bash "$RESOLVE" 2>&1
}
'''
assert text.count(old) == 1
text = text.replace(old, new)

old = '''rm -f "$ENVFILE" "$OUTFILE"

echo'''
new = '''rm -f "$ENVFILE" "$OUTFILE"

# 9. A prerelease version reaches PeroNPM and nothing else, whatever the caller asked
#    for: a version number on npmjs.org or nuget.org cannot be taken back.
out=$(resolve GITHUB_REF_NAME=0.3.0-preview.1 CHANNELS=peronpm,npmjs,nuget NUGET_PROJECT=Core/Core.csproj NUGET_USER=perotools NPM_URL=https://npm.example.com/ GITHUB_REPOSITORY=$repo); rc=$?
verify "a prerelease tag drops npmjs and nuget" "$rc" 0 "$out" "publishing to PeroNPM only"
contains_line "the prerelease is still published to PeroNPM" "$out" "DO_PERONPM=true"
contains_line "the prerelease is not published to npmjs" "$out" "DO_NPMJS=false"
contains_line "the prerelease is not published to nuget" "$out" "DO_NUGET=false"

# The old `-base` convention is a suffix like any other now.
out=$(resolve GITHUB_REF_NAME=0.3.0-base CHANNELS=peronpm,npmjs NUGET_PROJECT="" NUGET_USER="" NPM_URL=https://npm.example.com/ GITHUB_REPOSITORY=$repo); rc=$?
verify "a -base tag is a prerelease too" "$rc" 0 "$out" "DO_NPMJS=false"

# A tag that names no version stops the run before anything is packed.
out=$(resolve GITHUB_REF_NAME=nightly CHANNELS=peronpm NUGET_PROJECT="" NUGET_USER="" NPM_URL=https://npm.example.com/ GITHUB_REPOSITORY=$repo); rc=$?
verify "a tag that is not a version is refused" "$rc" 1 "$out" "invalid version tag 'nightly'"

echo'''
assert text.count(old) == 1
check.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
