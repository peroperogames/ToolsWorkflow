#!/bin/bash
# The channels a tag is allowed to publish to.
#
# A release — a version with no suffix — goes wherever the caller asked. Everything
# else goes to PeroNPM alone: a base release (`1.2.3-base`) is the same version built
# from the base branch, and a prerelease (`1.2.3-preview.1`) is the same source under a
# name that says it is not a release. Neither may take a version number on npmjs.org or
# nuget.org, because those cannot be taken back.
#
# This lives in one place because two callers need the same answer: the resolver, which
# decides what to publish, and the step that decides whether it has to find a project to
# pack at all.
#
#   bash channels_for_tag.sh "peronpm,npmjs,nuget" "1.2.3-base"   -> peronpm
#
set -uo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/version_from_tag.sh"

CHANNELS="${1:-peronpm}"
TAG="${2:-}"

if [ -n "$TAG" ] && ! is_release_tag "$TAG"; then
    # Validated here as well: a tag that names no version stops the run before
    # anything is packed, whether or not this release asks for the other channels.
    extract_version "$TAG" > /dev/null || exit 1
    echo "peronpm"
    exit 0
fi

printf '%s\n' "$CHANNELS"
