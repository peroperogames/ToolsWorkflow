#!/bin/bash
# Runs the version-bump steps against AccessKing's actual shape: the package
# manifest in Unity/, the .NET project at Core/ beside it, and the README with the
# install snippets at the repository root.
#
# The steps are the ones written in the workflow, extracted rather than copied, and
# they run in the order the workflow runs them. What this checks is that the bump
# reaches all three files and that the commit contains exactly them — not the
# packaging's renames, and not whatever else happened to be staged.
set -uo pipefail

TOOLS=/e/Gatongone/GitClone/ToolsWorkflow
WORK=/tmp/version-commit-layout
failures=0

ok() { echo "ok   $1"; }
bad() { echo "FAIL $1"; failures=$((failures + 1)); }
step() { python "$TOOLS/.scratch/run_workflow_step.py" "$1"; }

rm -rf "$WORK"
mkdir -p "$WORK/repo/Core" "$WORK/repo/Unity" "$WORK/repo/Legacy" "$WORK/runner-temp/devops/ToolsWorkflow"
cp -r "$TOOLS/publish" "$WORK/runner-temp/devops/ToolsWorkflow/publish"
export RUNNER_TEMP="$WORK/runner-temp"
REPO="$WORK/repo"

cat > "$REPO/Unity/package.json" <<'JSON'
{
  "name": "com.prpr.accessking",
  "displayName": "AccessKing",
  "version": "0.4.0"
}
JSON
cat > "$REPO/Core/PeroTools2.AccessKing.Core.csproj" <<'CSPROJ'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.1</TargetFramework>
    <Version>0.2.5</Version>
    <AssemblyVersion>0.2.5</AssemblyVersion>
    <FileVersion>0.2.5</FileVersion>
  </PropertyGroup>
</Project>
CSPROJ
cat > "$REPO/README.md" <<'MD'
# AccessKing

From NPMJS:

```json
{ "dependencies": { "com.prpr.accessking": "0.2.5" } }
```

```json
{ "dependencies": { "com.prpr.accessking": "https://github.com/peroperogames/AccessKing.git#v0.2.5" } }
```

```json
{ "dependencies": { "com.cysharp.unitask": "2.5.5" } }
```
MD
# The package's own README, which is what npm shows: when it exists the bump has to
# reach that one too, and both belong in the same commit.
cat > "$REPO/Unity/README.md" <<'MD'
# com.prpr.accessking

```json
{ "dependencies": { "com.prpr.accessking": "0.2.5" } }
```
MD
echo "keep" > "$REPO/Legacy/file.txt"
echo "notes" > "$REPO/Notes.md"

(cd "$REPO" && git init -q . && git config user.email t@example.com && git config user.name t \
  && git add -A && git commit -qm base) || bad "could not create the fixture repository"

# The packaging, as the workflow has already done it by the time these steps run:
# a folder moved the way changefoldername.sh moves it, a .meta deleted, and
# something else staged that the version commit must not take along.
(cd "$REPO" && mv Legacy "Legacy~" && rm -f Unity/whatever.meta && echo edited >> Notes.md && git add Notes.md)

# --- before the fix: the scan only saw the package directory -------------------
before_list="$WORK/version-files-before.txt"
(cd "$REPO/Unity" && NEW_VERSION=0.3.0 VERSION_FILE_LIST="$before_list" \
   bash "$RUNNER_TEMP/devops/ToolsWorkflow/publish/update_version_properties.sh") > "$WORK/before.log" 2>&1
if [ -s "$before_list" ]; then
  bad "the package-directory scan still finds files: $(cat "$before_list")"
elif grep -q '0.2.5' "$REPO/Core/PeroTools2.AccessKing.Core.csproj"; then
  ok "a scan of Unity/ alone never reaches Core/ (the bug this fixes)"
else
  bad "the csproj was rewritten by the package-directory scan"
fi

# --- the steps as the workflow runs them --------------------------------------
step "Package preprocess" > "$WORK/step-preprocess.sh"
step "Update the README's version" > "$WORK/step-readme.sh"
step "Update the assembly version properties" > "$WORK/step-props.sh"
step "Commit version update" > "$WORK/step-commit.sh"

run_in() { # directory, script, log, env assignments...
  local dir="$1" script="$2" log="$3"; shift 3
  ( cd "$dir" && env "$@" bash -e "$script" ) > "$log" 2>&1
}

run_in "$REPO/Unity" "$WORK/step-preprocess.sh" "$WORK/preprocess.log" \
  CI_COMMIT_TAG=0.3.0-base EXPECTED_PACKAGE_PREFIX=com.prpr PACKAGE_ROOT="$REPO/Unity"; rc=$?
[ "$rc" = 0 ] && ok "the preprocess rewrites the manifest" || { bad "preprocess exited $rc"; cat "$WORK/preprocess.log"; }

run_in "$REPO" "$WORK/step-readme.sh" "$WORK/readme.log" \
  CI_COMMIT_TAG=0.3.0-base PACKAGE_DIR=Unity; rc=$?
if [ "$rc" = 0 ] && grep -q '"com.prpr.accessking": "0.3.0"' "$REPO/README.md"; then
  ok "the repository README's install snippet is bumped"
else
  bad "the README step exited $rc: $(tail -3 "$WORK/readme.log")"
fi
if grep -q '"com.prpr.accessking": "https://github.com/peroperogames/AccessKing.git#0.3.0-base"' "$REPO/README.md"; then
  ok "the git# reference gets the tag, so the dead v0.2.5 link is fixed"
else
  bad "the git# reference was not rewritten: $(grep 'git#' "$REPO/README.md")"
fi
grep -q '"com.cysharp.unitask": "2.5.5"' "$REPO/README.md" \
  && ok "another package's version on the same page is left alone" \
  || bad "a dependency's version was rewritten"
if grep -q '"com.prpr.accessking": "0.3.0"' "$REPO/Unity/README.md"; then
  ok "the package's own README — the one npm shows — is bumped as well"
else
  bad "the package README was not bumped: $(cat "$REPO/Unity/README.md" 2>/dev/null)"
fi

run_in "$REPO" "$WORK/step-props.sh" "$WORK/props.log" PACKAGE_DIR=Unity; rc=$?
if [ "$rc" = 0 ] && grep -q '<Version>0.3.0</Version>' "$REPO/Core/PeroTools2.AccessKing.Core.csproj" \
   && grep -q '<AssemblyVersion>0.3.0</AssemblyVersion>' "$REPO/Core/PeroTools2.AccessKing.Core.csproj" \
   && grep -q '<FileVersion>0.3.0</FileVersion>' "$REPO/Core/PeroTools2.AccessKing.Core.csproj"; then
  ok "the .NET project gets the release version even though it is above working-directory"
else
  bad "the assembly properties were not bumped: $(grep -E '<(Version|AssemblyVersion|FileVersion)>' "$REPO/Core/PeroTools2.AccessKing.Core.csproj" | tr -d ' ' | tr '\n' ' ')"
fi

: > "$WORK/github-env"
run_in "$REPO" "$WORK/step-commit.sh" "$WORK/commit.log" PACKAGE_DIR=Unity GITHUB_ENV="$WORK/github-env"; rc=$?
if [ "$rc" = 0 ] && grep -q 'committed=true' "$WORK/github-env" 2>/dev/null; then
  ok "the version commit is made"
else
  bad "the commit step exited $rc: $(cat "$WORK/commit.log")"
fi

committed=$(cd "$REPO" && git show --name-only --format= HEAD 2>/dev/null | sort | tr '\n' ' ')
for want in README.md Core/PeroTools2.AccessKing.Core.csproj Unity/package.json Unity/README.md; do
  case " $committed " in
    *" $want "*) ok "the commit contains $want" ;;
    *) bad "the commit is missing $want (has: $committed)" ;;
  esac
done
case " $committed " in
  *" Notes.md "*) bad "the commit took the unrelated staged file along" ;;
  *) ok "the commit leaves the unrelated staged file alone" ;;
esac
if (cd "$REPO" && git show --name-only --format= HEAD | grep -q 'Legacy'); then
  bad "the commit took the packaging's folder rename along"
else
  ok "the commit leaves the packaging's rename out"
fi

if (cd "$REPO" && git status --porcelain | grep -q '^?? Legacy~/\|^ D Legacy/'); then
  ok "the packaging's rename is still uncommitted in the working tree"
fi

# --- a re-run finds the branch already carrying this version -------------------
# The job checks out the release tag, which is the commit from before the bump, while
# the branch was moved by the first run. Committing the same bump again is what made
# the rebase die on the rebuilt assembly (a binary both sides changed), so this case
# has to stop before the commit.
skip="$WORK/skip-case"
bare="$WORK/skip-origin.git"
rm -rf "$skip" "$bare"
mkdir -p "$skip/Unity"
git init -q --bare "$bare"
printf '{\n  "name": "com.prpr.accessking",\n  "version": "0.2.5"\n}\n' > "$skip/Unity/package.json"
( cd "$skip" && git init -q -b master . && git config user.email t@example.com && git config user.name t \
  && git remote add origin "$bare" && git add -A && git commit -qm base && git push -q -u origin master )
# the first run's bump is on the branch ...
( cd "$skip" && sed -i 's/0\.2\.5/0.3.0/' Unity/package.json \
  && git commit -qam "chore: update package version to 0.3.0." && git push -q origin master \
  && git reset -q --hard HEAD~1 )
# ... and the checkout is the pre-bump commit, preprocessed to the release version.
printf '{\n  "name": "com.prpr.accessking",\n  "version": "0.3.0"\n}\n' > "$skip/Unity/package.json"
: > "$WORK/github-env-skip"
run_in "$skip" "$WORK/step-commit.sh" "$WORK/skip.log" \
  PACKAGE_DIR=Unity TARGET_HINT=master GITHUB_ENV="$WORK/github-env-skip"; rc=$?
if [ "$rc" = 0 ] && grep -q 'already carries 0.3.0' "$WORK/skip.log"; then
  ok "a re-run does not push the version update the branch already has"
else
  bad "the re-run check exited $rc: $(tail -3 "$WORK/skip.log")"
fi
if grep -q 'committed=true' "$WORK/github-env-skip" 2>/dev/null; then
  bad "the re-run still committed, which is what broke the rebase"
else
  ok "... and asks for no push"
fi
if [ "$(cd "$skip" && git log -1 --format=%s)" = "base" ]; then
  ok "... nor does it create a commit"
else
  bad "the re-run created a commit: $(cd "$skip" && git log -1 --format=%s)"
fi

# The branch rule itself: a release that names a tag still resolves to the branch
# holding the tagged commit.
step "Commit version update" > /dev/null   # the script is called by the step, but also usable on its own
( cd "$skip" && git tag -f 0.2.5-base HEAD > /dev/null )
resolved=$( cd "$skip" && bash "$RUNNER_TEMP/devops/ToolsWorkflow/publish/release_target_branch.sh" "" "0.2.5-base" )
if [ "$resolved" = "master" ]; then
  ok "a release naming a tag resolves to the branch that holds it"
else
  bad "the branch rule resolved to '$resolved', wanted master"
fi
resolved=$( cd "$skip" && bash "$RUNNER_TEMP/devops/ToolsWorkflow/publish/release_target_branch.sh" "master" "" )
[ "$resolved" = "master" ] && ok "a release naming a branch resolves to that branch" \
  || bad "the branch rule resolved to '$resolved' for an explicit branch"
resolved=$( cd "$skip" && bash "$RUNNER_TEMP/devops/ToolsWorkflow/publish/release_target_branch.sh" "" "" )
[ -z "$resolved" ] && ok "nothing to go on resolves to nothing, not to a wrong branch" \
  || bad "the branch rule invented '$resolved'"

rm -rf "$WORK"
echo
if [ "$failures" -eq 0 ]; then echo "all version-commit checks passed"; else echo "$failures check(s) failed"; exit 1; fi
