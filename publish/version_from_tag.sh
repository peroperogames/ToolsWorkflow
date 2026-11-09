#!/bin/bash
# The version a release tag names. This file is sourced, not executed, because both
# the packaging which writes it into package.json and the NuGet step which passes it on
# the command line need the same answer, and two copies of a rule is how one release
# ends up publishing two different versions.
#
#   1.2.3             -> 1.2.3             a release: every channel asked for, announced
#   1.2.3-base        -> 1.2.3             a base release: PeroNPM only, announced
#   1.2.3-preview.1   -> 1.2.3-preview.1   a prerelease: PeroNPM only, silent
#   v1.2.3            -> 1.2.3             the same as 1.2.3
#
# `-base` is the tag a person creates for a release cut from the base branch, and it is
# the one the repository's tag Ruleset guards. It no longer publishes anywhere but
# PeroNPM: a version number on npmjs.org or nuget.org cannot be taken back, and a base
# release is one more build of the same source.
#
#   source version_from_tag.sh
#   VERSION=$(extract_version "$CI_COMMIT_TAG") || exit 1
#   if is_release_tag "$CI_COMMIT_TAG"; then ... fi

extract_version() {
    local tag="${1:-}"

    # 兼容可选的 v/V 前缀，这样 v1.2.3 和 1.2.3 是同一个版本。
    tag="${tag#v}"
    tag="${tag#V}"

    # `1.2.3-base` 是正式发布的一个分支名：版本是 1.2.3。
    if [[ $tag =~ ^([0-9]+\.[0-9]+\.[0-9]+)-base$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return 0
    fi

    # 其他后缀是预发布版本，版本号原样保留，`1.2.3-preview.1` 就该叫这个名字。
    if [[ $tag =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
        echo "$tag"
        return 0
    fi

    echo "Error: invalid version tag '$tag' (expected <version>, <version>-base or <version>-<suffix>)" >&2
    return 1
}

# The three questions the rest of the pipeline asks about a tag.
_strip_tag_prefix() {
    local tag="${1:-}"
    tag="${tag#v}"
    tag="${tag#V}"
    printf '%s' "$tag"
}

# A release: no suffix. It is the only shape that reaches npmjs.org and nuget.org.
is_release_tag() {
    [[ $(_strip_tag_prefix "${1:-}") =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

# A base release: the tag a person creates, guarded by the Ruleset, announced.
is_base_tag() {
    [[ $(_strip_tag_prefix "${1:-}") =~ ^[0-9]+\.[0-9]+\.[0-9]+-base$ ]]
}
