#!/bin/bash
# Put the version being published into the assembly/package version properties.
#
# A repository that also ships a NuGet package states the version again in
# `<Version>`, `<AssemblyVersion>` and `<FileVersion>` — in a `.csproj`, or in a
# `.props` shared by several projects. Nothing else bumps those, so they drift:
# AccessKing's Core project still said 0.2.5 while the Unity package had moved on.
#
#   NEW_VERSION=0.3.0 bash update_version_properties.sh
#   NEW_VERSION=1.2.3-android-variant bash update_version_properties.sh
#
# Only files that already carry one of these properties are rewritten — none is
# added, and no other element is touched. The numeric properties get the numeric
# core of the version, because `AssemblyVersion` and `FileVersion` do not accept the
# `-variant` suffix a pre-release uses:
#
#   <Version>0.3.0</Version>              <Version>1.2.3-android-variant</Version>
#   <AssemblyVersion>0.3.0</AssemblyVersion>   <AssemblyVersion>1.2.3</AssemblyVersion>
#   <FileVersion>0.3.0</FileVersion>           <FileVersion>1.2.3</FileVersion>
#
# The paths that changed are written, one per line, to $VERSION_FILE_LIST — the
# caller stages exactly those, because the working tree is dirty with the packaging
# renames and none of that may be committed.
set -uo pipefail

NEW_VERSION="${NEW_VERSION:-}"
VERSION_FILE_LIST="${VERSION_FILE_LIST:-}"

if [ -z "$NEW_VERSION" ]; then
    echo "Error: NEW_VERSION must be set" >&2
    exit 1
fi
if [ -n "$VERSION_FILE_LIST" ]; then
    : > "$VERSION_FILE_LIST"
fi

# 1.2.3-android-variant -> 1.2.3
NUMERIC_VERSION="${NEW_VERSION%%-*}"

changed=0
while IFS= read -r file; do
    # A cheap pre-check: most .props files have no version element at all.
    if ! grep -qE '<(Version|PackageVersion|AssemblyVersion|FileVersion|InformationalVersion)>' "$file"; then
        continue
    fi
    before=$(mktemp)
    cp -f "$file" "$before"
    sed -i -E \
        -e "s|<Version>[^<]*</Version>|<Version>${NEW_VERSION}</Version>|g" \
        -e "s|<PackageVersion>[^<]*</PackageVersion>|<PackageVersion>${NEW_VERSION}</PackageVersion>|g" \
        -e "s|<InformationalVersion>[^<]*</InformationalVersion>|<InformationalVersion>${NEW_VERSION}</InformationalVersion>|g" \
        -e "s|<AssemblyVersion>[^<]*</AssemblyVersion>|<AssemblyVersion>${NUMERIC_VERSION}</AssemblyVersion>|g" \
        -e "s|<FileVersion>[^<]*</FileVersion>|<FileVersion>${NUMERIC_VERSION}</FileVersion>|g" \
        "$file"
    if cmp -s "$before" "$file"; then
        rm -f "$before"
        continue
    fi
    echo "Updated $file:"
    diff -u "$before" "$file" | sed -n 's/^+\( *<\(Version\|PackageVersion\|AssemblyVersion\|FileVersion\|InformationalVersion\)>\)/  \1/p'
    rm -f "$before"
    changed=$((changed + 1))
    if [ -n "$VERSION_FILE_LIST" ]; then
        printf '%s\n' "$file" >> "$VERSION_FILE_LIST"
    fi
done < <(find . -type f \( -name '*.csproj' -o -name '*.props' -o -name '*.targets' \) \
             -not -path '*/obj/*' -not -path '*/bin/*' \
             -not -path '*/Library/*' -not -path '*~/*' | sort)

if [ "$changed" = 0 ]; then
    echo "No <Version>/<AssemblyVersion>/<FileVersion> property to update."
fi
