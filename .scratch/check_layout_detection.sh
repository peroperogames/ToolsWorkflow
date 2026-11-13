#!/bin/bash
# A caller no longer has to say where the package is or which project to pack: the
# repository does. This checks both answers against real layouts and against the awkward
# ones — a sample package nested deeper, a test project that must not be packed, two
# packable projects with and without a solution.
set -uo pipefail

TOOLS=/e/Gatongone/GitClone/ToolsWorkflow
PUBLISH="$TOOLS/publish"
failures=0

ok() { echo "ok   $1"; }
bad() { echo "FAIL $1"; failures=$((failures + 1)); }

expect() { # label, expected output, actual output, actual rc
  local label="$1" want="$2" got="$3" rc="$4"
  if [ "$rc" != 0 ]; then bad "$label: exit $rc ($got)"; return; fi
  if [ "$got" != "$want" ]; then bad "$label: '$got', wanted '$want'"; return; fi
  ok "$label -> $got"
}

expect_error() { # label, actual output, actual rc
  local label="$1" got="$2" rc="$3"
  if [ "$rc" = 0 ]; then bad "$label: exited 0 ($got)"; return; fi
  ok "$label refused: $(printf '%s' "$got" | head -1)"
}

work=/tmp/layout-detection
rm -rf "$work" && mkdir -p "$work"

# --- the package directory -------------------------------------------------------
mkdir -p "$work/root"
printf '{ "name": "com.prpr.root", "version": "1.0.0" }\n' > "$work/root/package.json"
got=$(bash "$PUBLISH/package_dir.sh" "$work/root"); rc=$?
expect "a package at the repository root" "." "$got" $rc

mkdir -p "$work/nested/Unity" "$work/nested/Samples/Example"
printf '{ "name": "com.prpr.nested", "version": "1.0.0" }\n' > "$work/nested/Unity/package.json"
printf '{ "name": "com.prpr.nested.example", "version": "0.0.1" }\n' > "$work/nested/Samples/Example/package.json"
got=$(bash "$PUBLISH/package_dir.sh" "$work/nested"); rc=$?
expect "the shallowest package wins over a nested sample" "Unity" "$got" $rc

got=$(bash "$PUBLISH/package_dir.sh" "$work/nested" "Samples/Example"); rc=$?
expect "a hint is honoured when it names a package" "Samples/Example" "$got" $rc

got=$(bash "$PUBLISH/package_dir.sh" "$work/nested" "NoSuchDir" 2>&1); rc=$?
expect_error "a hint that names no directory" "$got" $rc

mkdir -p "$work/nopkg/Runtime"
got=$(bash "$PUBLISH/package_dir.sh" "$work/nopkg" 2>&1); rc=$?
expect_error "a repository with no package.json" "$got" $rc

# --- the project the nuget channel packs -----------------------------------------
mkdir -p "$work/pack/Core" "$work/pack/Tests"
printf '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><PackageId>A.B</PackageId></PropertyGroup></Project>\n' > "$work/pack/Core/Core.csproj"
printf '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><IsPackable>false</IsPackable></PropertyGroup></Project>\n' > "$work/pack/Tests/Tests.csproj"
got=$(bash "$PUBLISH/nuget_project.sh" "$work/pack"); rc=$?
expect "the only packable project is packed" "Core/Core.csproj" "$got" $rc

touch "$work/pack/Solution.sln"
got=$(bash "$PUBLISH/nuget_project.sh" "$work/pack"); rc=$?
expect "one packable project is packed even with a solution beside it" "Core/Core.csproj" "$got" $rc

mkdir -p "$work/two/Core" "$work/two/Extra"
printf '<Project Sdk="Microsoft.NET.Sdk"/>\n' > "$work/two/Core/Core.csproj"
printf '<Project Sdk="Microsoft.NET.Sdk"/>\n' > "$work/two/Extra/Extra.csproj"
got=$(bash "$PUBLISH/nuget_project.sh" "$work/two" 2>&1); rc=$?
expect_error "two packable projects and no solution" "$got" $rc

touch "$work/two/Everything.sln"
got=$(bash "$PUBLISH/nuget_project.sh" "$work/two"); rc=$?
expect "two packable projects are packed through the solution" "Everything.sln" "$got" $rc

mkdir -p "$work/empty/Runtime"
got=$(bash "$PUBLISH/nuget_project.sh" "$work/empty" 2>&1); rc=$?
expect_error "a repository with no project" "$got" $rc

# --- and the real repositories ---------------------------------------------------
for pair in "CITest:." "accessking:Unity" "pero-serde:Unity"; do
  name=${pair%%:*}
  want=${pair##*:}
  path="/e/Gatongone/GitClone/$name"
  if [ ! -d "$path" ]; then continue; fi
  got=$(bash "$PUBLISH/package_dir.sh" "$path"); rc=$?
  expect "$name lays its package out where we think" "$want" "$got" $rc
done

if [ -d /e/Gatongone/GitClone/accessking ]; then
  got=$(bash "$PUBLISH/nuget_project.sh" /e/Gatongone/GitClone/accessking); rc=$?
  expect "accessking packs its Core project" "Core/PeroTools2.AccessKing.Core.csproj" "$got" $rc
fi
if [ -d /e/Gatongone/GitClone/pero-serde ]; then
  got=$(bash "$PUBLISH/nuget_project.sh" /e/Gatongone/GitClone/pero-serde); rc=$?
  expect "pero-serde packs its Core project, not the generator" "Core/PeroTools2.Serde.Core.csproj" "$got" $rc
fi
if [ -d /e/Gatongone/GitClone/CITest ]; then
  got=$(bash "$PUBLISH/nuget_project.sh" /e/Gatongone/GitClone/CITest 2>&1); rc=$?
  expect_error "CITest has no project to pack" "$got" $rc
fi

rm -rf "$work"
echo
if [ "$failures" -eq 0 ]; then echo "all layout checks passed"; else echo "$failures check(s) failed"; exit 1; fi
