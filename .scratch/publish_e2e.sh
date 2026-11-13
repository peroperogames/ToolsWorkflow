#!/bin/bash
# End-to-end check of the publish version steps in a throwaway git repo.
#
# Mirrors what the workflow does around them: package.json is preprocessed from the
# tag, the README and the assembly properties are rewritten, and the commit step
# commits exactly those — while the working tree also carries the packaging (folders
# moved, .meta deleted) and, worse, something already staged, neither of which may
# end up in the version commit.
set -uo pipefail

ROOT=/tmp/publish-e2e
TOOLS=/e/Gatongone/GitClone/ToolsWorkflow
rm -rf "$ROOT"
mkdir -p "$ROOT/Core"
cd "$ROOT" || exit 1

git init -q .
git config user.email "t@example.com"
git config user.name "t"

cat > package.json <<'JSON'
{
  "name": "com.prpr.accessking",
  "displayName": "AccessKing",
  "version": "0.2.5"
}
JSON
cat > README.md <<'MD'
# AccessKing

```json
{ "dependencies": { "com.prpr.accessking": "0.2.5" } }
```

```json
{ "dependencies": { "com.cysharp.unitask": "2.5.5" } }
```
MD
cat > Core/PeroTools2.AccessKing.Core.csproj <<'CSPROJ'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <Version>0.2.5</Version>
    <AssemblyVersion>0.2.5</AssemblyVersion>
    <FileVersion>0.2.5</FileVersion>
  </PropertyGroup>
</Project>
CSPROJ
mkdir -p Legacy
echo "keep" > Legacy/file.txt
echo "notes" > NOTES.md
git add -A
git commit -qm "base"

# The packaging, as changefoldername.sh does it: a plain mv and an rm, so the tree
# is dirty but nothing is staged by it.
mv Legacy Legacy~
rm -f Core/whatever.meta
# ... and something staged by something else, which a plain `git commit` would take
# along.
echo "edited" >> NOTES.md
git add NOTES.md

NEW_VERSION=0.3.0
sed -i "s/\(\"version\"\s*:\s*\)\"[^\"]*\"/\1\"$NEW_VERSION\"/" package.json
PACKAGE_NAME=com.prpr.accessking NEW_VERSION="$NEW_VERSION" GIT_REF=0.3.0-base \
  bash "$TOOLS/publish/update_readme_version.sh" README.md
export VERSION_FILE_LIST="$ROOT/version-files.txt"
NEW_VERSION="$NEW_VERSION" bash "$TOOLS/publish/update_version_properties.sh"

# The commit step.
FILES=(package.json)
if [ -f README.md ]; then FILES+=(README.md); fi
if [ -s "$VERSION_FILE_LIST" ]; then
  while IFS= read -r path; do FILES+=("$path"); done < "$VERSION_FILE_LIST"
fi
echo "--- files of the version commit ---"
printf '  %s\n' "${FILES[@]}"
if git diff --quiet -- "${FILES[@]}"; then
  echo "No changes to commit"
else
  git commit --only -qm "chore: update package version to $NEW_VERSION." -- "${FILES[@]}"
  echo "committed=true"
fi

echo "--- what the commit contains ---"
git show --stat --name-only --format="%s" HEAD | sed 's/^/  /'
echo "--- still dirty (must not be in the commit) ---"
git status --porcelain | sed 's/^/  /'
