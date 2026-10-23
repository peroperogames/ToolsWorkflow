#!/bin/bash
# The version a release tag names. This file is sourced, not executed, because two
# places need the same rule — the packaging which writes it into package.json, and
# the NuGet step which passes it on the command line — and two copies of a rule is
# how one release ends up publishing two different versions.
#
#   x.y.z-base       -> x.y.z            the plain release
#   x.y.z-x-variant  -> x.y.z-x-variant  a variant carries its own version
#   anything else    -> returns 1
#
#   source version_from_tag.sh
#   VERSION=$(extract_version "$CI_COMMIT_TAG") || exit 1

extract_version() {
    local tag="$1"

    # 兼容可选的 v/V 前缀，这样 v0.3.0-base 和 0.3.0-base 是同一个发布。
    tag="${tag#v}"
    tag="${tag#V}"

    # 规则 1：x.y.z-base -> 纯数字版本
    if [[ $tag =~ ^([0-9]+\.[0-9]+\.[0-9]+)-base$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return 0
    fi

    # 规则 2：x.y.z-x-variant -> 原样使用
    if [[ $tag =~ ^[0-9]+\.[0-9]+\.[0-9]+-.+-variant$ ]]; then
        echo "$tag"
        return 0
    fi

    # 规则 3：其他形式直接报错
    echo "Error: invalid version tag '$tag' (expected <version>-base or <version>-<x>-variant)" >&2
    return 1
}
