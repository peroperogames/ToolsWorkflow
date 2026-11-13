#!/bin/bash
# Runs the publish workflow's own step scripts — extracted from the YAML, not copied
# — against real tooling where that is possible, and against stubs where it is not:
# a folder feed stands in for nuget.org, and a recording `npm` stands in for
# registry.npmjs.org. Nothing here contacts a real registry, and no OIDC token is
# minted (that only happens on GitHub).
set -uo pipefail

TOOLS=/e/Gatongone/GitClone/ToolsWorkflow
WORK=/tmp/publish-steps
failures=0

ok() { echo "ok   $1"; }
bad() { echo "FAIL $1"; failures=$((failures + 1)); }

step() { python "$TOOLS/.scratch/run_workflow_step.py" "$1"; }
step_job() { python "$TOOLS/.scratch/run_workflow_step.py" --job "$1"; }

rm -rf "$WORK"
mkdir -p "$WORK/runner-temp/devops/ToolsWorkflow" "$WORK/bin" "$WORK/fixture/Core" "$WORK/feed" "$WORK/packages"
cp -r "$TOOLS/publish" "$WORK/runner-temp/devops/ToolsWorkflow/publish"
export RUNNER_TEMP="$WORK/runner-temp"

# The fixture: a packable project that says 0.2.5, and a test project that must not
# be packed (the same shape the SDK gives a test project).
cat > "$WORK/fixture/Core/PeroTools.Test.Core.csproj" <<'CSPROJ'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.0</TargetFramework>
    <AssemblyName>PeroTools.Test.Core</AssemblyName>
    <PackageId>PeroTools.Test.Core</PackageId>
    <Version>0.2.5</Version>
    <AssemblyVersion>0.2.5</AssemblyVersion>
    <FileVersion>0.2.5</FileVersion>
  </PropertyGroup>
</Project>
CSPROJ
cat > "$WORK/fixture/Core/Perotools.Test.Tests.csproj" <<'CSPROJ'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.0</TargetFramework>
    <IsPackable>false</IsPackable>
  </PropertyGroup>
</Project>
CSPROJ

# A packed tarball as the external job receives it.
make_tarball() { # destination, name, version, repository url (empty: no field)
  local out="$1" name="$2" version="$3" url="${4:-}" stage="$WORK/pack-stage"
  rm -rf "$stage" && mkdir -p "$stage/package"
  if [ -n "$url" ]; then
    printf '{"name":"%s","version":"%s","repository":{"type":"git","url":"%s"}}\n' "$name" "$version" "$url" > "$stage/package/package.json"
  else
    printf '{"name":"%s","version":"%s"}\n' "$name" "$version" > "$stage/package/package.json"
  fi
  tar -czf "$out" -C "$stage" package
}

step "Pack the NuGet packages" > "$WORK/step-pack.sh"
step "Collect the packages" > "$WORK/step-collect.sh"
step "Give the package the repository's README" > "$WORK/step-readme-copy.sh"
step "Publish to PeroNPM" > "$WORK/step-peronpm.sh"
step "Check the PeroNPM login" > "$WORK/step-login.sh"
step "Publish to npmjs" > "$WORK/step-npmjs.sh"
step "Push the NuGet packages" > "$WORK/step-push.sh"

for name in "Pack the NuGet packages:publish" "Publish to npmjs:external" "Push the NuGet packages:external" "Collect the packages:publish"; do
  want="${name##*:}"; got=$(step_job "${name%%:*}")
  [ "$want" = "$got" ] && ok "'${name%%:*}' runs in the $want job" || bad "'${name%%:*}' runs in '$got', expected $want"
done

# GitHub runs a `run:` block as `bash -e {0}`, so the tests do too.
run_step() { # script, workdir, log, env assignments...
  local script="$1" dir="$2" log="$3"; shift 3
  # PACKAGE_ROOT and PACKAGE_DIR are what the resolve step writes to $GITHUB_ENV; a step
  # that moves into the package reads the first of them.
  ( cd "$dir" && env PACKAGE_ROOT="$dir" PACKAGE_DIR="." "$@" bash -e "$script" ) > "$log" 2>&1
}

# --- the pack step, with the real SDK ------------------------------------------
run_step "$WORK/step-pack.sh" "$WORK/fixture" "$WORK/pack.log" \
  CI_COMMIT_TAG=0.3.0-base NUGET_PROJECT=Core/PeroTools.Test.Core.csproj; rc=$?
if [ "$rc" != 0 ]; then
  bad "pack exited $rc"; sed 's/^/    | /' "$WORK/pack.log"
elif [ -f "$RUNNER_TEMP/nuget/PeroTools.Test.Core.0.3.0.nupkg" ]; then
  ok "the pack step produces PeroTools.Test.Core.0.3.0.nupkg from a project that says 0.2.5"
else
  bad "no PeroTools.Test.Core.0.3.0.nupkg: $(ls "$RUNNER_TEMP/nuget" 2>/dev/null)"
fi
if grep -q '<Version>0.2.5</Version>' "$WORK/fixture/Core/PeroTools.Test.Core.csproj"; then
  ok "the pack did not rewrite the project's <Version>"
else
  bad "the pack rewrote the project's <Version>"
fi

# A variant tag names its own version, and the package carries it.
run_step "$WORK/step-pack.sh" "$WORK/fixture" "$WORK/pack-variant.log" \
  CI_COMMIT_TAG=0.4.0-ios-variant NUGET_PROJECT=Core/PeroTools.Test.Core.csproj; rc=$?
if [ "$rc" = 0 ] && [ -f "$RUNNER_TEMP/nuget/PeroTools.Test.Core.0.4.0-ios-variant.nupkg" ]; then
  ok "a variant tag packs PeroTools.Test.Core.0.4.0-ios-variant.nupkg"
else
  bad "the variant pack gave $rc and $(ls "$RUNNER_TEMP/nuget" 2>/dev/null | tr '\n' ' ')"
fi

# A project that is not there, and one the SDK refuses to pack.
run_step "$WORK/step-pack.sh" "$WORK/fixture" "$WORK/pack-missing.log" \
  CI_COMMIT_TAG=0.3.0-base NUGET_PROJECT=Nope/Nope.csproj; rc=$?
[ "$rc" != 0 ] && grep -q "the nuget-project input names the .csproj or .sln to pack" "$WORK/pack-missing.log" \
  && ok "a missing project is reported by name" || bad "a missing project gave $rc"
rm -rf "$RUNNER_TEMP/nuget"
run_step "$WORK/step-pack.sh" "$WORK/fixture" "$WORK/pack-unpackable.log" \
  CI_COMMIT_TAG=0.3.0-base NUGET_PROJECT=Core/Perotools.Test.Tests.csproj; rc=$?
[ "$rc" != 0 ] && grep -q "produced no .nupkg" "$WORK/pack-unpackable.log" \
  && ok "a non-packable project is a failure" || bad "a non-packable project gave $rc"

# --- collecting the artifact ----------------------------------------------------
run_step "$WORK/step-pack.sh" "$WORK/fixture" "$WORK/pack-again.log" \
  CI_COMMIT_TAG=0.3.0-base NUGET_PROJECT=Core/PeroTools.Test.Core.csproj
cat > "$WORK/fixture/package.json" <<'JSON'
{
  "name": "com.prpr.accessking",
  "displayName": "AccessKing",
  "version": "0.4.0",
  "repository": { "type": "git", "url": "https://github.com/peroperogames/AccessKing" }
}
JSON
run_step "$WORK/step-collect.sh" "$WORK/fixture" "$WORK/collect.log"; rc=$?
if [ "$rc" = 0 ] && [ -f "$RUNNER_TEMP/publish-artifacts/com.prpr.accessking-0.4.0.tgz" ]; then
  ok "the collect step packs the tarball the other registry publishes"
else
  bad "collect exited $rc: $(tail -3 "$WORK/collect.log")"
fi
if ls "$RUNNER_TEMP/publish-artifacts/" | grep -q '\.nupkg$'; then
  ok "the collected artifact also carries the .nupkg"
else
  bad "the .nupkg was not collected"
fi

# --- rebuilding the assembly the package ships ---------------------------------
# A package that ships a precompiled DLL keeps a second copy of the version inside
# that DLL. The properties step only changes the source, so without a rebuild the
# published package carries the previous build's binary — and the NuGet package of
# the same version, built from source, carries a different one.
plugin_case="$WORK/plugin-case"
rm -rf "$plugin_case" && mkdir -p "$plugin_case/Core" "$plugin_case/Unity/Plugins"
cat > "$plugin_case/Core/Perotools.Test.Plugin.csproj" <<'CSPROJ'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.0</TargetFramework>
    <AssemblyName>Perotools.Test.Plugin</AssemblyName>
    <Configurations>Debug;Release;Unity</Configurations>
    <Version>0.2.5</Version>
    <AssemblyVersion>0.2.5</AssemblyVersion>
    <FileVersion>0.2.5</FileVersion>
  </PropertyGroup>
  <Target Name="CopyToUnityPackage" AfterTargets="Build" Condition="'$(Configuration)' == 'Unity'">
    <Copy SourceFiles="$(TargetPath)" DestinationFolder="$(MSBuildThisFileDirectory)../Unity/Plugins/" SkipUnchangedFiles="true"/>
  </Target>
</Project>
CSPROJ
echo "public class PerotoolsTestPlugin { }" > "$plugin_case/Core/Plugin.cs"
printf '{\n  "name": "com.prpr.accessking",\n  "version": "0.3.0"\n}\n' > "$plugin_case/Unity/package.json"
printf 'the previous build\n' > "$plugin_case/Unity/Plugins/Perotools.Test.Plugin.dll"
( cd "$plugin_case" && git init -q . && git config user.email t@example.com && git config user.name t \
  && git add -A && git commit -qm base )

step "Update the assembly version properties" > "$WORK/step-props.sh"
step "Rebuild the assembly the package ships" > "$WORK/step-rebuild.sh"

: > "$RUNNER_TEMP/version-files.txt"
run_step "$WORK/step-props.sh" "$plugin_case" "$WORK/plugin-props.log" PACKAGE_DIR=Unity; rc=$?
[ "$rc" = 0 ] && ok "the properties step bumps the project first" \
  || bad "the properties step exited $rc: $(cat "$WORK/plugin-props.log")"

run_step "$WORK/step-rebuild.sh" "$plugin_case" "$WORK/plugin-rebuild.log" \
  PACKAGE_DIR=Unity PLUGIN_PROJECT=Core/Perotools.Test.Plugin.csproj PLUGIN_CONFIGURATION=Unity; rc=$?
if [ "$rc" = 0 ] && grep -qa '0\.3\.0' "$plugin_case/Unity/Plugins/Perotools.Test.Plugin.dll"; then
  ok "the rebuilt assembly in the package carries the release version"
else
  bad "the rebuild exited $rc: $(tail -3 "$WORK/plugin-rebuild.log")"
fi
if grep -qxF 'Unity/Plugins/Perotools.Test.Plugin.dll' "$RUNNER_TEMP/version-files.txt"; then
  ok "the refreshed assembly joins the version commit"
else
  bad "the refreshed assembly is not in the commit list: $(cat "$RUNNER_TEMP/version-files.txt")"
fi
if ( cd "$plugin_case" && git status --porcelain -- Unity/Plugins | grep -q '^ M Unity/Plugins/Perotools.Test.Plugin.dll' ); then
  ok "the assembly really changed in the working tree"
else
  bad "the assembly did not change in the working tree"
fi
# The packaging's own changes must stay out of that list.
( cd "$plugin_case" && mkdir -p Unity/Gone && echo x > Unity/Gone/x.txt && git rm -q -r --cached Unity/Gone > /dev/null 2>&1; rm -rf Unity/Gone )
: > "$RUNNER_TEMP/version-files.txt"
run_step "$WORK/step-rebuild.sh" "$plugin_case" "$WORK/plugin-rebuild2.log" \
  PACKAGE_DIR=Unity PLUGIN_PROJECT=Core/Perotools.Test.Plugin.csproj PLUGIN_CONFIGURATION=Unity; rc=$?
if [ "$rc" = 0 ] && ! grep -q 'Deleted' "$RUNNER_TEMP/version-files.txt"; then
  ok "a second build only re-adds what it changed"
else
  bad "the second build's list: $(cat "$RUNNER_TEMP/version-files.txt")"
fi

run_step "$WORK/step-rebuild.sh" "$plugin_case" "$WORK/plugin-missing.log" \
  PACKAGE_DIR=Unity PLUGIN_PROJECT=Nope/Nope.csproj PLUGIN_CONFIGURATION=Unity; rc=$?
[ "$rc" != 0 ] && grep -q 'unity-plugin-project names the .csproj or .sln' "$WORK/plugin-missing.log" \
  && ok "a missing plugin project is reported by name" || bad "a missing plugin project gave $rc"

# --- the repository README inside the published package ------------------------
# npm shows the README that is in the tarball; a README at the repository root has
# to be copied into the package for that, and only when the package has none.
readme_case="$WORK/readme-case"
rm -rf "$readme_case" && mkdir -p "$readme_case/Unity" "$WORK/npm-pack"
printf '# AccessKing\n\nthe documentation\n' > "$readme_case/README.md"
printf '{"name":"com.prpr.accessking","version":"0.3.0"}\n' > "$readme_case/Unity/package.json"

run_step "$WORK/step-readme-copy.sh" "$readme_case" "$WORK/copy.log" PACKAGE_DIR=Unity; rc=$?
if [ "$rc" = 0 ] && cmp -s "$readme_case/README.md" "$readme_case/Unity/README.md"; then
  ok "the repository README is copied into the package"
else
  bad "the README copy exited $rc: $(tail -2 "$WORK/copy.log")"
fi

# ... and that is what makes it appear in the tarball the registries receive.
( cd "$readme_case/Unity" && npm pack --pack-destination "$WORK/npm-pack" > /dev/null 2>&1 )
if tar -tzf "$WORK"/npm-pack/*.tgz 2>/dev/null | grep -qx 'package/README.md'; then
  ok "the packed tarball carries README.md, which is the one npm shows"
else
  bad "the tarball has no package/README.md"
fi

printf '# the package has its own\n' > "$readme_case/Unity/README.md"
run_step "$WORK/step-readme-copy.sh" "$readme_case" "$WORK/copy-own.log" PACKAGE_DIR=Unity; rc=$?
if [ "$rc" = 0 ] && grep -q 'the package has its own' "$readme_case/Unity/README.md"; then
  ok "a package with a README of its own keeps it"
else
  bad "the copy overwrote the package's own README"
fi
rm -f "$readme_case/Unity/README.md"

run_step "$WORK/step-readme-copy.sh" "$readme_case" "$WORK/copy-root.log" PACKAGE_DIR=.; rc=$?
if [ "$rc" = 0 ] && grep -q 'already inside it' "$WORK/copy-root.log"; then
  ok "a package at the repository root needs no copy"
else
  bad "the working-directory '.' case exited $rc: $(cat "$WORK/copy-root.log")"
fi

mv "$readme_case/README.md" "$readme_case/README.md.gone"
run_step "$WORK/step-readme-copy.sh" "$readme_case" "$WORK/copy-none.log" PACKAGE_DIR=Unity; rc=$?
if [ "$rc" = 0 ] && grep -q 'no README.md at the repository root' "$WORK/copy-none.log"; then
  ok "a repository without a README is not an error"
else
  bad "a repository without a README gave $rc: $(cat "$WORK/copy-none.log")"
fi

# --- the two npm steps, with a recording npm -----------------------------------
cat > "$WORK/bin/npm" <<'STUB'
#!/bin/bash
# Answers --version, records every publish, and installs "successfully" if asked.
if [ "$1" = "--version" ]; then
  if [ -s "$STUB_VERSION_FILE" ]; then cat "$STUB_VERSION_FILE"; else echo "${STUB_NPM_VERSION:-11.6.0}"; fi
  exit 0
fi
printf '%s\n' "$*" >> "$STUB_LOG"
if [ "$1" = "install" ]; then
  [ "${STUB_UPGRADE:-0}" = 1 ] && echo "11.6.0" > "$STUB_VERSION_FILE"
  exit 0
fi
count=$(cat "$STUB_COUNT" 2>/dev/null || echo 0)
count=$((count + 1))
echo "$count" > "$STUB_COUNT"
if [ "$count" -le "${STUB_FAIL_UNTIL:-0}" ]; then
  echo "stub npm: attempt $count fails" >&2
  if [ -n "${STUB_FAIL_FILE:-}" ] && [ -f "$STUB_FAIL_FILE" ]; then cat "$STUB_FAIL_FILE" >&2; fi
  exit "${STUB_FAIL_CODE:-1}"
fi
exit 0
STUB
cat > "$WORK/bin/sleep" <<'STUB'
#!/bin/bash
# The retries wait five seconds each; the tests do not.
exit 0
STUB
chmod +x "$WORK/bin/npm" "$WORK/bin/sleep"
export PATH="$WORK/bin:$PATH"
STUB_VERSION_FILE="$WORK/npm-version"

reset_stub() { rm -f "$WORK/npm.log" "$WORK/npm.count" "$STUB_VERSION_FILE"; }
stub_env() { # extra assignments for the stub
  printf 'STUB_LOG=%s STUB_COUNT=%s STUB_VERSION_FILE=%s %s' \
    "$WORK/npm.log" "$WORK/npm.count" "$STUB_VERSION_FILE" "$1"
}

# PeroNPM keeps publishing exactly as it did: same registry, same retry.
reset_stub
# shellcheck disable=SC2046
run_step "$WORK/step-peronpm.sh" "$WORK/fixture" "$WORK/peronpm.log" \
  NPM_URL=https://npm.example.com/ $(stub_env "STUB_FAIL_CODE=1"); rc=$?
if [ "$rc" = 0 ] && grep -qx 'publish --registry https://npm.example.com/ --verbose' "$WORK/npm.log"; then
  ok "PeroNPM publishes to \$NPM_URL, unchanged"
else
  bad "PeroNPM: rc=$rc, args=$(cat "$WORK/npm.log" 2>/dev/null)"
fi

# The login check only warns: the runner's ~/.npmrc is not the workflow's business.
reset_stub
# shellcheck disable=SC2046
run_step "$WORK/step-login.sh" "$WORK/fixture" "$WORK/login.log" \
  NPM_URL=http://127.0.0.1:1/ $(stub_env "STUB_FAIL_CODE=1"); rc=$?
[ "$rc" = 0 ] && ok "a missing PeroNPM login warns instead of failing the run" || bad "the login check exited $rc"

# A re-run of a release finds its version already in the registry. That is the state
# the run wanted to reach, so it must not fail — retrying it never succeeds.
cat > "$WORK/npm-error-409.txt" <<'ERR'
npm error code E409
npm error 409 Conflict - PUT https://npm.example.com/com.prpr.accessking - cannot publish over previously published version 0.3.0
npm error A complete log of this run can be found in: /home/runner/.npm/_logs/debug-0.log
ERR
reset_stub
# shellcheck disable=SC2046
run_step "$WORK/step-peronpm.sh" "$WORK/fixture" "$WORK/peronpm-409.log" \
  NPM_URL=https://npm.example.com/ $(stub_env "STUB_FAIL_CODE=1 STUB_FAIL_UNTIL=1 STUB_FAIL_FILE=$WORK/npm-error-409.txt"); rc=$?
attempts=$(grep -c '^publish ' "$WORK/npm.log")
if [ "$rc" = 0 ] && [ "$attempts" = 1 ] && grep -q 'already in PeroNPM' "$WORK/peronpm-409.log"; then
  ok "a version PeroNPM already has is not retried and not a failure"
else
  bad "already published on PeroNPM: rc=$rc, attempts=$attempts, log=$(tail -2 "$WORK/peronpm-409.log")"
fi

# A publish that fails for any other reason still fails, after the retries.
cat > "$WORK/npm-error-other.txt" <<'ERR'
npm error code E404
npm error 404 Not Found - PUT https://npm.example.com/com.prpr.accessking
ERR
reset_stub
# shellcheck disable=SC2046
run_step "$WORK/step-peronpm.sh" "$WORK/fixture" "$WORK/peronpm-404.log" \
  NPM_URL=https://npm.example.com/ $(stub_env "STUB_FAIL_CODE=1 STUB_FAIL_FILE=$WORK/npm-error-other.txt STUB_FAIL_UNTIL=99"); rc=$?
attempts=$(grep -c '^publish ' "$WORK/npm.log")
[ "$rc" != 0 ] && [ "$attempts" = 3 ] && ok "any other publish failure still fails after three attempts" \
  || bad "a 404 publish: rc=$rc, attempts=$attempts"

# --- npmjs: trusted publishing, no credential at all ---------------------------
npm_fixture() { # repository url
  rm -rf "$WORK/external" && mkdir -p "$WORK/external/packages"
  make_tarball "$WORK/external/packages/com.prpr.accessking-0.4.0.tgz" com.prpr.accessking 0.4.0 "$1"
}

npm_fixture "https://github.com/peroperogames/AccessKing"
reset_stub
# shellcheck disable=SC2046
run_step "$WORK/step-npmjs.sh" "$WORK/external" "$WORK/npmjs.log" \
  ACTIONS_ID_TOKEN_REQUEST_URL=https://example.invalid/token GITHUB_REPOSITORY=peroperogames/AccessKing \
  $(stub_env "STUB_FAIL_CODE=1"); rc=$?
args=$(head -1 "$WORK/npm.log" 2>/dev/null)
# Absolute, and it has to be: `npm publish packages/x.tgz` is the GitHub shorthand
# owner/repo to npm, which turns into `git ls-remote ssh://git@github.com/packages/x.tgz.git`.
if [ "$rc" = 0 ] && [ "$args" = "publish $WORK/external/packages/com.prpr.accessking-0.4.0.tgz --registry https://registry.npmjs.org/" ]; then
  ok "npmjs publishes the packed tarball to the public registry"
else
  bad "npmjs: rc=$rc, args=$args, log=$(tail -2 "$WORK/npmjs.log")"
fi
if printf '%s' "$args" | grep -qiE 'userconfig|authtoken|_auth|token=' ; then
  bad "the npmjs publish carries a credential: $args"
else
  ok "the npmjs publish carries no credential"
fi

# The OIDC token is granted by the calling workflow, so its absence has to be
# explained rather than surface as ENEEDAUTH from npm.
npm_fixture "https://github.com/peroperogames/AccessKing"
reset_stub
# shellcheck disable=SC2046
run_step "$WORK/step-npmjs.sh" "$WORK/external" "$WORK/npmjs-noidc.log" \
  ACTIONS_ID_TOKEN_REQUEST_URL="" GITHUB_REPOSITORY=peroperogames/AccessKing \
  $(stub_env "STUB_FAIL_CODE=1"); rc=$?
if [ "$rc" != 0 ] && grep -q 'id-token: write' "$WORK/npmjs-noidc.log"; then
  ok "no OIDC token is reported as a missing id-token permission"
else
  bad "no OIDC: rc=$rc, log=$(tail -2 "$WORK/npmjs-noidc.log")"
fi

# npm too old for trusted publishing: said plainly, and raised if possible.
npm_fixture "https://github.com/peroperogames/AccessKing"
reset_stub
# shellcheck disable=SC2046
run_step "$WORK/step-npmjs.sh" "$WORK/external" "$WORK/npmjs-old.log" \
  ACTIONS_ID_TOKEN_REQUEST_URL=https://example.invalid/token GITHUB_REPOSITORY=peroperogames/AccessKing \
  $(stub_env "STUB_FAIL_CODE=1 STUB_NPM_VERSION=10.9.0 STUB_UPGRADE=0"); rc=$?
if [ "$rc" != 0 ] && grep -q 'still older than 11.5.1' "$WORK/npmjs-old.log"; then
  ok "an npm too old for trusted publishing fails with the version named"
else
  bad "old npm: rc=$rc, log=$(tail -3 "$WORK/npmjs-old.log")"
fi

npm_fixture "https://github.com/peroperogames/AccessKing"
reset_stub
# shellcheck disable=SC2046
run_step "$WORK/step-npmjs.sh" "$WORK/external" "$WORK/npmjs-upgrade.log" \
  ACTIONS_ID_TOKEN_REQUEST_URL=https://example.invalid/token GITHUB_REPOSITORY=peroperogames/AccessKing \
  $(stub_env "STUB_FAIL_CODE=1 STUB_NPM_VERSION=10.9.0 STUB_UPGRADE=1"); rc=$?
if [ "$rc" = 0 ] && grep -q 'install --global npm@\^11' "$WORK/npm.log"; then
  ok "an npm too old is upgraded before publishing"
else
  bad "upgrade: rc=$rc, log=$(cat "$WORK/npm.log" 2>/dev/null)"
fi

# Retries, and the failure after the last one.
npm_fixture "https://github.com/peroperogames/AccessKing"
reset_stub
# shellcheck disable=SC2046
run_step "$WORK/step-npmjs.sh" "$WORK/external" "$WORK/npmjs-retry.log" \
  ACTIONS_ID_TOKEN_REQUEST_URL=https://example.invalid/token GITHUB_REPOSITORY=peroperogames/AccessKing \
  $(stub_env "STUB_FAIL_CODE=1 STUB_FAIL_UNTIL=2"); rc=$?
attempts=$(grep -c '^publish ' "$WORK/npm.log")
if [ "$rc" = 0 ] && [ "$attempts" = 3 ] && grep -q 'Attempt 2 failed' "$WORK/npmjs-retry.log"; then
  ok "a flaky registry is retried and then succeeds (3 attempts)"
else
  bad "retry: rc=$rc, attempts=$attempts"
fi
npm_fixture "https://github.com/peroperogames/AccessKing"
reset_stub
# shellcheck disable=SC2046
run_step "$WORK/step-npmjs.sh" "$WORK/external" "$WORK/npmjs-fail.log" \
  ACTIONS_ID_TOKEN_REQUEST_URL=https://example.invalid/token GITHUB_REPOSITORY=peroperogames/AccessKing \
  $(stub_env "STUB_FAIL_CODE=1 STUB_FAIL_UNTIL=99"); rc=$?
attempts=$(grep -c '^publish ' "$WORK/npm.log")
[ "$rc" != 0 ] && [ "$attempts" = 3 ] && ok "a registry that keeps failing fails the step after 3 attempts" \
  || bad "permanent failure: rc=$rc, attempts=$attempts"

# repository.url, which npm refuses a trusted publish without.
npm_fixture ""
reset_stub
# shellcheck disable=SC2046
run_step "$WORK/step-npmjs.sh" "$WORK/external" "$WORK/npmjs-norepo.log" \
  ACTIONS_ID_TOKEN_REQUEST_URL=https://example.invalid/token GITHUB_REPOSITORY=peroperogames/AccessKing \
  $(stub_env "STUB_FAIL_CODE=1"); rc=$?
[ "$rc" = 0 ] && grep -q 'has no repository.url' "$WORK/npmjs-norepo.log" \
  && ok "a package.json without repository.url is called out" || bad "missing repository.url: rc=$rc"

npm_fixture "https://git.peropero.net/unity-packages/dear-imgui"
reset_stub
# shellcheck disable=SC2046
run_step "$WORK/step-npmjs.sh" "$WORK/external" "$WORK/npmjs-wrongrepo.log" \
  ACTIONS_ID_TOKEN_REQUEST_URL=https://example.invalid/token GITHUB_REPOSITORY=peroperogames/AccessKing \
  $(stub_env "STUB_FAIL_CODE=1"); rc=$?
[ "$rc" = 0 ] && grep -q 'does not name https://github.com/peroperogames/AccessKing' "$WORK/npmjs-wrongrepo.log" \
  && ok "a repository.url naming another repository is called out" || bad "wrong repository.url: rc=$rc"

# Two tarballs where one is expected is a failure, not a guess.
npm_fixture "https://github.com/peroperogames/AccessKing"
cp "$WORK/external/packages/com.prpr.accessking-0.4.0.tgz" "$WORK/external/packages/other-1.0.0.tgz"
reset_stub
# shellcheck disable=SC2046
run_step "$WORK/step-npmjs.sh" "$WORK/external" "$WORK/npmjs-two.log" \
  ACTIONS_ID_TOKEN_REQUEST_URL=https://example.invalid/token GITHUB_REPOSITORY=peroperogames/AccessKing \
  $(stub_env "STUB_FAIL_CODE=1"); rc=$?
[ "$rc" != 0 ] && grep -q 'Expected exactly one packed tarball' "$WORK/npmjs-two.log" \
  && ok "two tarballs are refused" || bad "two tarballs: rc=$rc"

export PATH="${PATH#"$WORK/bin:"}"

# --- the nuget push, against a folder feed -------------------------------------
rm -rf "$RUNNER_TEMP/nuget" && mkdir -p "$RUNNER_TEMP/nuget"
run_step "$WORK/step-pack.sh" "$WORK/fixture" "$WORK/pack-final.log" \
  CI_COMMIT_TAG=0.3.0-base NUGET_PROJECT=Core/PeroTools.Test.Core.csproj
rm -rf "$WORK/external" && mkdir -p "$WORK/external/packages"
cp "$RUNNER_TEMP"/nuget/*.nupkg "$WORK/external/packages/"

run_step "$WORK/step-push.sh" "$WORK/external" "$WORK/push.log" \
  NUGET_SOURCE="$WORK/feed" NUGET_API_KEY=k3y; rc=$?
if [ "$rc" = 0 ] && ls "$WORK/feed" | grep -q '^PeroTools.Test.Core.0.3.0.nupkg$'; then
  ok "the push step puts the package in the feed"
else
  bad "the push step exited $rc: $(tail -3 "$WORK/push.log")"
fi
grep -q 'k3y' "$WORK/push.log" && bad "the API key was printed" || ok "the API key is not in the log"

run_step "$WORK/step-push.sh" "$WORK/external" "$WORK/push-again.log" \
  NUGET_SOURCE="$WORK/feed" NUGET_API_KEY=k3y; rc=$?
[ "$rc" = 0 ] && ok "a re-run of the push succeeds" || bad "the re-run exited $rc: $(tail -3 "$WORK/push-again.log")"

run_step "$WORK/step-push.sh" "$WORK/external" "$WORK/push-nokey.log" \
  NUGET_SOURCE="$WORK/feed" NUGET_API_KEY=""; rc=$?
[ "$rc" != 0 ] && grep -q 'returned no API key' "$WORK/push-nokey.log" \
  && ok "a missing nuget.org key is a failure" || bad "missing key: rc=$rc"

mkdir -p "$WORK/empty/packages"
run_step "$WORK/step-push.sh" "$WORK/empty" "$WORK/push-empty.log" \
  NUGET_SOURCE="$WORK/feed" NUGET_API_KEY=k3y; rc=$?
[ "$rc" != 0 ] && grep -q 'no .nupkg in packages/' "$WORK/push-empty.log" \
  && ok "pushing nothing is a failure" || bad "pushing nothing gave $rc"

run_step "$WORK/step-push.sh" "$WORK/external" "$WORK/push-bad.log" \
  NUGET_SOURCE="$WORK/not-a-feed-file" NUGET_API_KEY=k3y; rc=$?
[ "$rc" != 0 ] && grep -q 'after 3 attempts' "$WORK/push-bad.log" \
  && ok "a rejected push fails after three attempts" || bad "a rejected push gave $rc"

rm -rf "$WORK"
echo
if [ "$failures" -eq 0 ]; then echo "all publish step checks passed"; else echo "$failures check(s) failed"; exit 1; fi
