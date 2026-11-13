#!/bin/bash
# Checks that the `channels` input resolves the way the workflow's jobs assume:
# PeroNPM by default, npmjs/nuget only when named, and a refusal — not a silent
# fallback — when a channel is missing something it needs.
set -uo pipefail

TOOLS=/e/Gatongone/GitClone/ToolsWorkflow
RESOLVE="$TOOLS/publish/resolve_channels.sh"
failures=0

verify() { # label, actual_rc, expected_rc, actual_out, expected_substring
  local label="$1" arc="$2" erc="$3" aout="$4" want="$5"
  if [ "$arc" != "$erc" ]; then
    echo "FAIL $label: expected exit $erc, got $arc"
    printf '%s\n' "$aout" | sed 's/^/    | /'
    failures=$((failures + 1))
    return
  fi
  if [ -n "$want" ] && ! printf '%s' "$aout" | grep -qF -- "$want"; then
    echo "FAIL $label: output lacks '$want'"
    printf '%s\n' "$aout" | sed 's/^/    | /'
    failures=$((failures + 1))
    return
  fi
  echo "ok   $label"
}

contains_line() { # label, output, exact line
  if printf '%s\n' "$2" | grep -qxF -- "$3"; then echo "ok   $1"; else
    echo "FAIL $1: output has no line '$3'"; printf '%s\n' "$2" | sed 's/^/    | /'; failures=$((failures + 1))
  fi
}

# Each case is a private environment, so nothing leaks between them. A release tag is
# the default: a version with no suffix is what publishes to every channel.
resolve() { # env assignments..., then runs the resolver
  env GITHUB_REF_NAME=0.3.0 "$@" bash "$RESOLVE" 2>&1
}

repo=peroperogames/AccessKing

# 1. Nothing asked for: PeroNPM, which is what every release publishes today.
out=$(resolve CHANNELS="" NUGET_PROJECT="" NUGET_USER="" NPM_URL=https://npm.example.com/ GITHUB_REPOSITORY=$repo); rc=$?
verify "empty channels -> peronpm only" "$rc" 0 "$out" "Publishing to: PeroNPM"
contains_line "DO_PERONPM is true" "$out" "DO_PERONPM=true"
contains_line "DO_NPMJS is false" "$out" "DO_NPMJS=false"
contains_line "DO_NUGET is false" "$out" "DO_NUGET=false"

# 2. npmjs needs no credential at all, only the repository OIDC will prove.
out=$(resolve CHANNELS=peronpm,npmjs NUGET_PROJECT="" NUGET_USER="" NPM_URL=https://npm.example.com/ GITHUB_REPOSITORY=$repo); rc=$?
verify "npmjs needs no token" "$rc" 0 "$out" "DO_NPMJS=true"
verify "npmjs says whose trusted publisher it is" "$rc" 0 "$out" "OIDC trusted publisher of $repo"
verify "npmjs names the file to configure" "$rc" 0 "$out" "CALLING workflow file"
out=$(resolve CHANNELS=npmjs NUGET_PROJECT="" NUGET_USER="" NPM_URL="" GITHUB_REPOSITORY=""); rc=$?
verify "npmjs without a repository is refused" "$rc" 1 "$out" "GITHUB_REPOSITORY"

# 3. nuget needs the project it packs and the profile the policy belongs to.
out=$(resolve CHANNELS=nuget NUGET_PROJECT="" NUGET_USER=perotools NPM_URL="" GITHUB_REPOSITORY=$repo); rc=$?
verify "nuget without a project is refused" "$rc" 1 "$out" "nuget-project"
out=$(resolve CHANNELS=nuget NUGET_PROJECT=Core/Core.csproj NUGET_USER="" NPM_URL="" GITHUB_REPOSITORY=$repo); rc=$?
verify "nuget without a user is refused" "$rc" 1 "$out" "nuget-user"

# 4. nuget alone, nothing else: uploading to one registry does not imply the others.
out=$(resolve CHANNELS=nuget NUGET_PROJECT=Core/Core.csproj NUGET_USER=perotools NPM_URL="" GITHUB_REPOSITORY=$repo); rc=$?
verify "nuget alone" "$rc" 0 "$out" "DO_NUGET=true"
contains_line "nuget alone leaves PeroNPM off" "$out" "DO_PERONPM=false"

# 5. All three, written the way a human writes a list: capitals, spaces, newline.
out=$(resolve CHANNELS=$'PeroNPM, NPMJS\nNuGet' NUGET_PROJECT=Core/Core.csproj NUGET_USER=perotools NPM_URL=https://npm.example.com/ GITHUB_REPOSITORY=$repo); rc=$?
verify "all three, messy spacing" "$rc" 0 "$out" "Publishing to: PeroNPM, npmjs, NuGet"
contains_line " ' NPMJS' still counts" "$out" "DO_NPMJS=true"

# 6. A typo must not degrade into "publish to PeroNPM anyway".
out=$(resolve CHANNELS=peronpm,openupm NUGET_PROJECT="" NUGET_USER="" NPM_URL=https://npm.example.com/ GITHUB_REPOSITORY=$repo); rc=$?
verify "unknown channel is refused" "$rc" 1 "$out" "unknown publish channel 'openupm'"

# 7. PeroNPM needs its registry URL; a run without PeroNPM does not.
out=$(resolve CHANNELS=peronpm NUGET_PROJECT="" NUGET_USER="" NPM_URL="" GITHUB_REPOSITORY=$repo); rc=$?
verify "peronpm without NPM_URL is refused" "$rc" 1 "$out" "NPM_URL"
out=$(resolve CHANNELS=nuget NUGET_PROJECT=Core/Core.csproj NUGET_USER=perotools NPM_URL="" GITHUB_REPOSITORY=$repo); rc=$?
verify "a nuget-only run needs no NPM_URL" "$rc" 0 "$out" "DO_NUGET=true"

# 8. $GITHUB_ENV drives this job's steps, $GITHUB_OUTPUT the other jobs.
ENVFILE=/tmp/gh_env_channels_test
OUTFILE=/tmp/gh_output_channels_test
rm -f "$ENVFILE" "$OUTFILE"
out=$(resolve CHANNELS=peronpm,npmjs NUGET_PROJECT="" NUGET_USER="" NPM_URL=https://npm.example.com/ GITHUB_REPOSITORY=$repo GITHUB_ENV="$ENVFILE" GITHUB_OUTPUT="$OUTFILE"); rc=$?
verify "writes to GITHUB_ENV and GITHUB_OUTPUT" "$rc" 0 "$out" "DO_NPMJS=true"
contains_line "GITHUB_ENV carries DO_NPMJS" "$(cat "$ENVFILE" 2>/dev/null)" "DO_NPMJS=true"
contains_line "GITHUB_OUTPUT carries DO_NPMJS" "$(cat "$OUTFILE" 2>/dev/null)" "DO_NPMJS=true"
contains_line "GITHUB_OUTPUT carries DO_NUGET" "$(cat "$OUTFILE" 2>/dev/null)" "DO_NUGET=false"
rm -f "$ENVFILE" "$OUTFILE"

# 9. A base release is the tag a person creates; it reaches PeroNPM and nothing else,
#    whatever the caller asked for.
out=$(resolve GITHUB_REF_NAME=0.3.0-preview.1 CHANNELS=peronpm,npmjs,nuget NUGET_PROJECT=Core/Core.csproj NUGET_USER=perotools NPM_URL=https://npm.example.com/ GITHUB_REPOSITORY=$repo); rc=$?
verify "a prerelease tag drops npmjs and nuget" "$rc" 0 "$out" "publishing to PeroNPM only"
contains_line "the prerelease is still published to PeroNPM" "$out" "DO_PERONPM=true"
contains_line "the prerelease is not published to npmjs" "$out" "DO_NPMJS=false"
contains_line "the prerelease is not published to nuget" "$out" "DO_NUGET=false"

out=$(resolve GITHUB_REF_NAME=0.3.0-base CHANNELS=peronpm,npmjs NUGET_PROJECT="" NUGET_USER="" NPM_URL=https://npm.example.com/ GITHUB_REPOSITORY=$repo); rc=$?
verify "a -base tag is published to PeroNPM only" "$rc" 0 "$out" "base release"
contains_line "the base release is not published to npmjs" "$out" "DO_NPMJS=false"

# A release — no suffix at all — is the one shape that reaches the other registries.
out=$(resolve GITHUB_REF_NAME=0.3.0 CHANNELS=peronpm,npmjs NUGET_PROJECT="" NUGET_USER="" NPM_URL=https://npm.example.com/ GITHUB_REPOSITORY=$repo); rc=$?
verify "a release reaches npmjs" "$rc" 0 "$out" "DO_NPMJS=true"

# A tag that names no version stops the run before anything is packed.
out=$(resolve GITHUB_REF_NAME=nightly CHANNELS=peronpm NUGET_PROJECT="" NUGET_USER="" NPM_URL=https://npm.example.com/ GITHUB_REPOSITORY=$repo); rc=$?
verify "a tag that is not a version is refused" "$rc" 1 "$out" "invalid version tag 'nightly'"

echo
if [ "$failures" -eq 0 ]; then echo "all channel checks passed"; else echo "$failures check(s) failed"; exit 1; fi
