#!/bin/bash
# Turn the `channels` input into the flags the publish steps ask about.
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
# Writes the flags to $GITHUB_ENV when it is set, to stdout otherwise, so the same
# script is what the workflow runs and what a test can run.
set -uo pipefail

CHANNELS="${CHANNELS:-peronpm}"
NUGET_PROJECT="${NUGET_PROJECT:-}"

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

if [ "$want_npmjs" = true ] && [ -z "${NPMJS_TOKEN:-}" ]; then
    echo "Error: the npmjs channel needs the NPMJS_TOKEN secret; a release cannot publish to registry.npmjs.org without it" >&2
    exit 1
fi

if [ "$want_peronpm" = true ] && [ -z "${NPM_URL:-}" ]; then
    echo "Error: the peronpm channel needs the NPM_URL secret (the registry URL)" >&2
    exit 1
fi

if [ "$want_nuget" = true ]; then
    if [ -z "$NUGET_PROJECT" ]; then
        echo "Error: the nuget channel needs the nuget-project input (the .csproj or .sln to pack)" >&2
        exit 1
    fi
    if [ -z "${NUGET_API_KEY:-}" ]; then
        echo "Error: the nuget channel needs the NUGET_API_KEY secret" >&2
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
printf '%s\n' "$lines"
