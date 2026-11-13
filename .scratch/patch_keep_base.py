"""One-off: keep `-base`, publish it to PeroNPM only, and announce it.

The tag rules are now:

  1.2.3            a release      every channel that was asked for, announced
  1.2.3-base       a base release PeroNPM only, announced
  1.2.3-preview.1  a prerelease   PeroNPM only, silent

`-base` is what the Ruleset guards, so it stays the name a person creates; it just no
longer reaches npmjs.org or nuget.org, whose version numbers cannot be taken back.
"""

from pathlib import Path

root = Path(__file__).resolve().parent.parent
version_sh = root / "publish" / "version_from_tag.sh"
resolver = root / "publish" / "resolve_channels.sh"
workflow = root / ".github" / "workflows" / "publish-npm.yml"
readme = root / "publish" / "README.md"


def replace(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, (text.count(old), old[:70])
    return text.replace(old, new)


# --------------------------------------------------------------------------- #
# The tag rule.
# --------------------------------------------------------------------------- #
version_sh.write_text(
    '''#!/bin/bash
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
    if [[ $tag =~ ^([0-9]+\\.[0-9]+\\.[0-9]+)-base$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return 0
    fi

    # 其他后缀是预发布版本，版本号原样保留，`1.2.3-preview.1` 就该叫这个名字。
    if [[ $tag =~ ^[0-9]+\\.[0-9]+\\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
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
    [[ $(_strip_tag_prefix "${1:-}") =~ ^[0-9]+\\.[0-9]+\\.[0-9]+$ ]]
}

# A base release: the tag a person creates, guarded by the Ruleset, announced.
is_base_tag() {
    [[ $(_strip_tag_prefix "${1:-}") =~ ^[0-9]+\\.[0-9]+\\.[0-9]+-base$ ]]
}
''',
    encoding="utf-8",
    newline="\n",
)

# --------------------------------------------------------------------------- #
# Only a release reaches the registries outside PeroNPM.
# --------------------------------------------------------------------------- #
text = resolver.read_text(encoding="utf-8")
text = replace(
    text,
    '''# 这次发布用的是哪个 tag。带后缀的是预发布版本（`1.2.3-preview.1`），只发
# PeroNPM：npmjs.org 与 nuget.org 上不可撤回的版本号属于正式发布，而预发布只是同一
# 份源码换了个名字，不该占用它们。
TRIGGER_TAG="${GITHUB_REF_NAME:-${TAG:-${CI_COMMIT_TAG:-}}}"
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
''',
    '''# 这次发布用的是哪个 tag。只有无后缀的正式版本（`1.2.3`）会发到 PeroNPM 以外的
# 注册表：npmjs.org 与 nuget.org 上的版本号不可撤回，`1.2.3-base` 是同一个版本从
# base 分支出的另一次构建，`1.2.3-preview.1` 是预发布，两者都只发 PeroNPM。
TRIGGER_TAG="${GITHUB_REF_NAME:-${TAG:-${CI_COMMIT_TAG:-}}}"
source "$(dirname "${BASH_SOURCE[0]}")/version_from_tag.sh"
if [ -n "$TRIGGER_TAG" ]; then
    VERSION=$(extract_version "$TRIGGER_TAG") || exit 1
    if ! is_release_tag "$TRIGGER_TAG"; then
        if is_base_tag "$TRIGGER_TAG"; then
            echo "tag '$TRIGGER_TAG' is a base release ($VERSION): publishing to PeroNPM only, whatever else was asked for."
        else
            echo "tag '$TRIGGER_TAG' is a prerelease version ($VERSION): publishing to PeroNPM only, whatever else was asked for."
        fi
        CHANNELS="peronpm"
    fi
else
    echo "No release tag in the environment; publishing to the channels as asked."
fi
''',
)
resolver.write_text(text, encoding="utf-8", newline="\n")

# --------------------------------------------------------------------------- #
# A release and a base release are announced; a variant is not.
# --------------------------------------------------------------------------- #
text = workflow.read_text(encoding="utf-8")
text = replace(
    text,
    """      # A version with no suffix is a release, and a release is announced. A
      # prerelease (`1.2.3-preview.1`) was announced by whoever published it, and it
      # reaches PeroNPM alone.
      ${{ !cancelled()
          && needs.publish.result == 'success'
          && (needs.external.result == 'success' || needs.external.result == 'skipped')
          && !contains(github.ref_name, '-') }}""",
    """      # A release (`1.2.3`) and a base release (`1.2.3-base`) are announced; a
      # variant (`1.2.3-android-variant`) is a build of the same source for a
      # different target and is published to PeroNPM alone, unannounced.
      ${{ !cancelled()
          && needs.publish.result == 'success'
          && (needs.external.result == 'success' || needs.external.result == 'skipped')
          && (!contains(github.ref_name, '-') || endsWith(github.ref_name, '-base')) }}""",
)
workflow.write_text(text, encoding="utf-8", newline="\n")

# --------------------------------------------------------------------------- #
# The docs.
# --------------------------------------------------------------------------- #
doc = readme.read_text(encoding="utf-8")
doc = replace(
    doc,
    """| `0.3.0` | `0.3.0` |
| `v0.3.0` | `0.3.0` |""",
    """| `0.3.0` | `0.3.0` |
| `v0.3.0` | `0.3.0` |
| `0.3.0-base` | `0.3.0` |""",
)
doc = replace(
    doc,
    "| Send Feishu notification (`notify`) | Only for a release tag — a version with no suffix — and only when every channel that ran came out green. |",
    "| Send Feishu notification (`notify`) | For a release (`0.3.0`) and a base release (`0.3.0-base`); never for a variant. Only when every channel that ran came out green. |",
)
doc = replace(
    doc,
    """A tag with a suffix is a prerelease: `1.2.3-preview.1` is published to PeroNPM alone and
is not announced. The suffix in a tag is what says "the same source under a name that
says it is not a release" — everything else is a release.

Releases created under the old `1.2.3-base` convention keep their tags; OpenUPM can be
told to ignore them with `gitTagIgnore: '-base$'` in the package's metadata, and a
`1.2.3` tag on the version commit. New releases need neither.""",
    """A base release — `1.2.3-base`, the tag a person creates and the one the repository's
tag Ruleset guards — is published to PeroNPM alone and announced. So is a variant
(`1.2.3-android-variant`), except that a variant is not announced: it is the same source
built for another target. Only a tag with no suffix at all reaches npmjs.org and
nuget.org, whose version numbers cannot be taken back.

For OpenUPM, tell it to ignore the tags it cannot read with `gitTagIgnore: '-base$'` in
the package's metadata, and give it the version tag: `1.2.3` on the commit that carries
`package.json` `1.2.3` (the version commit this workflow pushes).""",
)
readme.write_text(doc, encoding="utf-8", newline="\n")
print("patched")
