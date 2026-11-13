#!/bin/bash
# Runs the workflow's own resolve step against real repositories.
#
# The step is lifted out of publish-npm.yml rather than copied, so what is tested is the
# script that will run: it must find the package, find the project the nuget channel
# packs, and hand the three answers to the rest of the job.
set -uo pipefail

TOOLS=/e/Gatongone/GitClone/ToolsWorkflow
WORKFLOW="$TOOLS/.github/workflows/publish-npm.yml"
failures=0

ok() { echo "ok   $1"; }
bad() { echo "FAIL $1"; failures=$((failures + 1)); }

work=/tmp/resolve-step
rm -rf "$work" && mkdir -p "$work/devops"
cp -r "$TOOLS" "$work/devops/ToolsWorkflow"
rm -rf "$work/devops/ToolsWorkflow/.git"

# The step's script, lifted out by indentation: what runs is the file's own text, not a
# copy that could drift from it.
awk '
  /- name: Resolve the package directory and the NuGet project/ { found = 1 }
  found && /^        run: \|$/ { capture = 1; next }
  capture && /^$/ { print ""; next }
  capture && /^          / { sub(/^          /, ""); print; next }
  capture { exit }
' "$WORKFLOW" > "$work/step.sh"
if [ ! -s "$work/step.sh" ]; then
  echo "FAIL could not lift the resolve step out of $WORKFLOW"
  exit 1
fi

run_case() { # label, repo path, channels, expected shard|value...
  local label="$1" repo="$2" channels="$3"; shift 3
  local envfile="$work/env-$RANDOM.txt" outfile="$work/out-$RANDOM.txt"
  : > "$envfile"; : > "$outfile"
  local out rc
  out=$(cd "$repo" && env \
    RUNNER_TEMP="$work" \
    GITHUB_WORKSPACE="$repo" \
    GITHUB_ENV="$envfile" \
    GITHUB_OUTPUT="$outfile" \
    GITHUB_REPOSITORY="peroperogames/$(basename "$repo")" \
    HINT_DIR="" HINT_NUGET="" HINT_USER="Peropero" \
    CHANNELS="$channels" \
    NPM_URL="https://npm.example.com/" \
    bash "$work/step.sh" 2>&1); rc=$?
  if [ "$rc" != 0 ]; then
    bad "$label: exit $rc"; printf '%s\n' "$out" | sed 's/^/    | /'; return
  fi
  local want key value actual failed=0
  for want in "$@"; do
    key=${want%%=*}
    value=${want#*=}
    actual=$(grep -E "^${key}=" "$envfile" "$outfile" 2>/dev/null | head -1 | cut -d= -f2-)
    if [ "$actual" != "$value" ]; then
      bad "$label: $key='$actual', wanted '$value'"; failed=1
    fi
  done
  [ "$failed" = 0 ] && ok "$label"
}

# CITest: package at the root, no project, PeroNPM only.
run_case "CITest, peronpm only" /e/Gatongone/GitClone/CITest "peronpm" \
  "PACKAGE_DIR=." "DO_PERONPM=true" "DO_NPMJS=false" "DO_NUGET=false"

# AccessKing: package in Unity/, project beside it, all three channels.
run_case "AccessKing, all channels" /e/Gatongone/GitClone/accessking "peronpm,npmjs,nuget" \
  "PACKAGE_DIR=Unity" "NUGET_PROJECT=Core/PeroTools2.AccessKing.Core.csproj" \
  "DO_PERONPM=true" "DO_NPMJS=true" "DO_NUGET=true"

# PeroSerde: same shape, and the packable project is Core rather than the generator.
run_case "PeroSerde, all channels" /e/Gatongone/GitClone/pero-serde "peronpm,npmjs,nuget" \
  "PACKAGE_DIR=Unity" "NUGET_PROJECT=Core/PeroTools2.Serde.Core.csproj" "DO_NUGET=true"

# A base tag keeps PeroNPM and drops the rest, whatever the caller asked for.
: > "$work/env-base.txt"; : > "$work/out-base.txt"
out=$(cd /e/Gatongone/GitClone/CITest && env \
  RUNNER_TEMP="$work" GITHUB_WORKSPACE=/e/Gatongone/GitClone/CITest \
  GITHUB_ENV="$work/env-base.txt" GITHUB_OUTPUT="$work/out-base.txt" \
  GITHUB_REPOSITORY=peroperogames/CITest GITHUB_REF_NAME=0.3.0-base \
  HINT_DIR="" HINT_NUGET="" HINT_USER="Peropero" CHANNELS="peronpm,npmjs,nuget" \
  NPM_URL="https://npm.example.com/" bash "$work/step.sh" 2>&1)
if grep -q '^DO_NPMJS=false' "$work/env-base.txt" && grep -q '^DO_PERONPM=true' "$work/env-base.txt"; then
  ok "a base tag resolves to PeroNPM only"
else
  bad "a base tag kept the other channels: $(cat "$work/env-base.txt" | tr '\n' ' ')"
fi

# A caller that names the wrong directory fails here, not three steps later.
out=$(cd /e/Gatongone/GitClone/CITest && env \
  RUNNER_TEMP="$work" GITHUB_WORKSPACE=/e/Gatongone/GitClone/CITest \
  GITHUB_ENV="$work/env-bad.txt" GITHUB_OUTPUT="$work/out-bad.txt" \
  GITHUB_REPOSITORY=peroperogames/CITest \
  HINT_DIR="NoSuchDir" HINT_NUGET="" HINT_USER="Peropero" CHANNELS="peronpm" \
  NPM_URL="https://npm.example.com/" bash "$work/step.sh" 2>&1); rc=$?
if [ "$rc" != 0 ] && printf '%s' "$out" | grep -q "does not exist"; then
  ok "a hint that names nothing stops the run"
else
  bad "a bad hint gave exit $rc: $(printf '%s' "$out" | head -2 | tr '\n' ' ')"
fi

rm -rf "$work"
echo
if [ "$failures" -eq 0 ]; then echo "all resolve-step checks passed"; else echo "$failures check(s) failed"; exit 1; fi
