"""One-off: suffix-less versions, and a suffixed tag belongs to PeroNPM alone.

`-base` was a marker for "a release cut from the base branch", and it turned out to be
the thing OpenUPM cannot read: it takes a tag as the version. Now the version is the
tag, a tag with a suffix is a prerelease that only PeroNPM receives, and nothing about
`-base` survives.
"""

from pathlib import Path

root = Path(__file__).resolve().parent.parent
version_sh = root / "publish" / "version_from_tag.sh"
channels_sh = root / "publish" / "resolve_channels.sh"
workflow = root / ".github" / "workflows" / "publish-npm.yml"
readme = root / "publish" / "README.md"

# --------------------------------------------------------------------------- #
# The tag is the version. A suffix makes it a prerelease, not a different rule.
# --------------------------------------------------------------------------- #
version_sh.write_text(
    '''#!/bin/bash
# The version a release tag names. This file is sourced, not executed, because both
# the packaging which writes it into package.json and the NuGet step which passes it
# on the command line need the same answer, and two copies of a rule is how one
# release ends up publishing two different versions.
#
# The version IS the tag, with an optional `v` in front:
#
#   1.2.3            -> 1.2.3            a release: every channel, and a notification
#   1.2.3-preview.1  -> 1.2.3-preview.1  a prerelease: PeroNPM only, no notification
#   v1.2.3           -> 1.2.3            the same release
#
# Anything that is not a version is refused: a tag the registry would reject is not a
# release, and the build stops before anything is packed.
#
#   source version_from_tag.sh
#   VERSION=$(extract_version "$CI_COMMIT_TAG") || exit 1
#   if is_release_tag "$CI_COMMIT_TAG"; then ... fi

extract_version() {
    local tag="${1:-}"

    # 兼容可选的 v/V 前缀，这样 v1.2.3 和 1.2.3 是同一个版本。
    tag="${tag#v}"
    tag="${tag#V}"

    # semver 的正式部分必须是三段数字；带后缀的是预发布版本，原样保留。
    if [[ $tag =~ ^[0-9]+\\.[0-9]+\\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
        echo "$tag"
        return 0
    fi

    echo "Error: invalid version tag '$tag' (expected <version>, optionally with a -suffix)" >&2
    return 1
}

# A release is a tag with no suffix at all: `1.2.3`, not `1.2.3-base` and not
# `1.2.3-preview.1`. Only a release reaches the registries other than PeroNPM, and
# only a release is announced — a prerelease is the same source published under a
# name that says it is not one.
is_release_tag() {
    local tag="${1:-}"
    tag="${tag#v}"
    tag="${tag#V}"
    [[ $tag =~ ^[0-9]+\\.[0-9]+\\.[0-9]+$ ]]
}
''',
    encoding="utf-8",
    newline="\n",
)

# --------------------------------------------------------------------------- #
# A suffixed tag is published to PeroNPM alone, whatever the caller asked for.
# --------------------------------------------------------------------------- #
text = channels_sh.read_text(encoding="utf-8")
old = '''CHANNELS="${CHANNELS:-peronpm}"
NUGET_PROJECT="${NUGET_PROJECT:-}"
NUGET_USER="${NUGET_USER:-}"
'''
new = '''CHANNELS="${CHANNELS:-peronpm}"
NUGET_PROJECT="${NUGET_PROJECT:-}"
NUGET_USER="${NUGET_USER:-}"

# 这次发布用的是哪个 tag。带后缀的是预发布版本（`1.2.3-preview.1`），只发
# PeroNPM：npmjs.org 与 nuget.org 上不可撤回的版本号属于正式发布，而预发布只是同一
# 份源码换了个名字，不该占用它们。
TRIGGER_TAG="${GITHUB_REF_NAME:-${TAG:-${CI_COMMIT_TAG:-}}}"
source "$(dirname "${BASH_SOURCE[0]}")/version_from_tag.sh"
VERSION=$(extract_version "$TRIGGER_TAG") || exit 1
if ! is_release_tag "$TRIGGER_TAG"; then
    if [ "$CHANNELS" != "peronpm" ]; then
        echo "tag '$TRIGGER_TAG' is a prerelease version ($VERSION): publishing to PeroNPM only, whatever else was asked for."
    fi
    CHANNELS="peronpm"
fi
'''
text = text.replace(old, new)
channels_sh.write_text(text, encoding="utf-8", newline="\n")

# --------------------------------------------------------------------------- #
# notify: a release announces itself, a prerelease does not.
# --------------------------------------------------------------------------- #
text = workflow.read_text(encoding="utf-8")
old = """      if: ${{
        needs.publish.result == 'success'
        && (needs.external.result == 'success' || needs.external.result == 'skipped')
        && endsWith(github.ref_name, '-base') }}"""
new = """      # A prerelease is announced by whoever published it; only a version with no
      # suffix is a release the whole ecosystem gets.
      if: ${{
        needs.publish.result == 'success'
        && (needs.external.result == 'success' || needs.external.result == 'skipped')
        && !contains(github.ref_name, '-') }}"""
assert text.count(old) == 1, text.count(old)
text = text.replace(old, new)

# The extra OpenUPM tag existed because the release tag was not a version. It is one
# now, so the step goes.
start = text.index("           # OpenUPM builds a package from a tag and takes the tag as the version, so")
end = text.index("      # npm shows the README that is inside the published tarball")
text = text[:start] + "\n" + text[end:]
workflow.write_text(text, encoding="utf-8", newline="\n")

# --------------------------------------------------------------------------- #
# The docs.
# --------------------------------------------------------------------------- #
doc = readme.read_text(encoding="utf-8")
section_start = doc.index("## OpenUPM\n")
section_end = doc.index("## What goes where\n")
doc = doc[:section_start] + """## OpenUPM

OpenUPM builds a package from a **tag**, and it takes that tag as the version: it
compares the tag against `package.json` at that commit and refuses the build when they
differ (`E811 package.json version does not match release version`). A release is
therefore tagged with the version itself — `1.2.3` — and the version commit this
workflow pushes carries `package.json` with the same `1.2.3`, so there is nothing to
reconcile. A tag such as `1.2.3-preview.1` is a prerelease, published to PeroNPM only.

""" + doc[section_end:]
readme.write_text(doc, encoding="utf-8", newline="\n")
print("patched")
