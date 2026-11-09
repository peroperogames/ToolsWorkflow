#!/bin/bash
# Turn the `channels` input into the flags the publish jobs ask about.
#
# PeroNPM is the registry these packages are read from — the one every release
# publishes to today — so it is the default and needs nothing from the caller.
# npmjs and nuget are somebody else's registry, and a release that ships to one of
# them by accident cannot be taken back; both are opt-in, named explicitly.
#
#   channels: peronpm                  (default)
#   channels: peronpm,npmjs
#   channels: peronpm,npmjs,nuget
#
# Neither of the two other channels takes a credential: both authenticate with
# OIDC trusted publishing, which the job exchanges for a short-lived token at
# publish time. What they do need is known before anything is built — that is
# what this checks.
#
# Writes the flags to $GITHUB_ENV and $GITHUB_OUTPUT when set, to stdout always,
# so the same script is what the workflow runs and what a test can run.
set -uo pipefail

CHANNELS="${CHANNELS:-peronpm}"
NUGET_PROJECT="${NUGET_PROJECT:-}"
NUGET_USER="${NUGET_USER:-}"

# 这次发布用的是哪个 tag。只有无后缀的正式版本（`1.2.3`）会发到 PeroNPM 以外的
# 注册表：npmjs.org 与 nuget.org 上的版本号不可撤回，`1.2.3-base` 是同一个版本从
# base 分支出的另一次构建，`1.2.3-preview.1` 是预发布，两者都只发 PeroNPM。规则本身
# 在 channels_for_tag.sh 里，那个脚本的另一个用途是让调用方知道"要不要准备 nuget 的
# 工程"。
here="$(dirname "${BASH_SOURCE[0]}")"
TRIGGER_TAG="${GITHUB_REF_NAME:-${TAG:-${CI_COMMIT_TAG:-}}}"
source "$here/version_from_tag.sh"
if [ -n "$TRIGGER_TAG" ]; then
    VERSION=$(extract_version "$TRIGGER_TAG") || exit 1
    if ! is_release_tag "$TRIGGER_TAG"; then
        if is_base_tag "$TRIGGER_TAG"; then
            echo "tag '$TRIGGER_TAG' is a base release ($VERSION): publishing to PeroNPM only, whatever else was asked for."
        else
            echo "tag '$TRIGGER_TAG' is a prerelease version ($VERSION): publishing to PeroNPM only, whatever else was asked for."
        fi
    fi
else
    echo "No release tag in the environment; publishing to the channels as asked."
fi
CHANNELS=$(bash "$here/channels_for_tag.sh" "$CHANNELS" "$TRIGGER_TAG") || exit 1

want_peronpm=false
want_npmjs=false
want_nuget=false

# 逗号、空格、换行都当分隔符，因为调用方是手写这个列表的。
normalised=$(printf '%s' "$CHANNELS" | tr ',' ' ' | tr '\n' ' ' | tr '[:upper:]' '[:lower:]')

for channel in $normalised; do
    case "$channel" in
        peronpm) want_peronpm=true ;;
        npmjs) want_npmjs=true ;;
        nuget) want_nuget=true ;;
        *)
            echo "Error: unknown publish channel '$channel' (expected peronpm, npmjs, nuget)" >&2
            echo "Refusing to publish, because the list was not understood." >&2
            exit 1
            ;;
    esac
done

if [ "$want_peronpm" = false ] && [ "$want_npmjs" = false ] && [ "$want_nuget" = false ]; then
    echo "Error: no publish channel given; PeroNPM is the default and has to be named to publish only it" >&2
    exit 1
fi

if [ "$want_peronpm" = true ] && [ -z "${NPM_URL:-}" ]; then
    echo "Error: the peronpm channel needs the NPM_URL secret (the registry URL)" >&2
    exit 1
fi

if [ "$want_npmjs" = true ]; then
    # Publishing to registry.npmjs.org with OIDC needs two things in the calling
    # repository which this workflow cannot arrange for it.
    if [ -z "${GITHUB_REPOSITORY:-}" ]; then
        echo "Error: the npmjs channel needs GITHUB_REPOSITORY to name the trusted publisher" >&2
        exit 1
    fi
    echo "npmjs: publishing as OIDC trusted publisher of $GITHUB_REPOSITORY;"
    echo "       its trusted publisher on npmjs.com must name this repository and the CALLING workflow file."
fi

if [ "$want_nuget" = true ]; then
    if [ -z "$NUGET_PROJECT" ]; then
        echo "Error: the nuget channel needs the nuget-project input (the .csproj or .sln to pack)" >&2
        exit 1
    fi
    if [ -z "$NUGET_USER" ]; then
        echo "Error: the nuget channel needs the nuget-user input (the nuget.org profile the trusted publishing policy belongs to)" >&2
        exit 1
    fi
fi

enabled=()
if [ "$want_peronpm" = true ]; then enabled+=(PeroNPM); fi
if [ "$want_npmjs" = true ]; then enabled+=(npmjs); fi
if [ "$want_nuget" = true ]; then enabled+=(NuGet); fi
# 日志里只出现一次"这次到底发到哪儿了"，出问题时不用回头去数 if。
echo "Publishing to: $(printf '%s, ' "${enabled[@]}" | sed 's/, $//')"

lines="DO_PERONPM=$want_peronpm
DO_NPMJS=$want_npmjs
DO_NUGET=$want_nuget"

if [ -n "${GITHUB_ENV:-}" ]; then
    printf '%s\n' "$lines" >> "$GITHUB_ENV"
fi
# The other jobs are told the same three answers through the job outputs: the
# external channels publish from a GitHub-hosted job, which never sees this one's
# environment.
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    printf '%s\n' "$lines" >> "$GITHUB_OUTPUT"
fi
printf '%s\n' "$lines"
