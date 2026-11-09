#!/bin/bash
# Which project the `nuget` channel packs.
#
# The caller may name it (`nuget-project`), but the answer is in the repository: the
# project that is packable — no `<IsPackable>false</IsPackable>`, which test and bench
# projects carry — and a solution at the root when there is more than one, because
# `dotnet pack <sln>` packs every packable project in it and a release that ships two
# packages should not need two inputs.
#
#   bash nuget_project.sh <repo root> [hint]
#
# Prints the path relative to the repository root, or exits non-zero with a reason.
set -uo pipefail

ROOT="${1:-.}"
HINT="${2:-}"

if [ ! -d "$ROOT" ]; then
    echo "Error: '$ROOT' is not a directory" >&2
    exit 1
fi

if [ -n "$HINT" ]; then
    if [ ! -e "$ROOT/$HINT" ]; then
        echo "Error: nuget-project '$HINT' does not exist in the repository" >&2
        exit 1
    fi
    printf '%s\n' "$HINT"
    exit 0
fi

# Every project that would produce a package. `IsPackable` is the switch the SDK reads:
# absent means true, and a test or bench project says false.
packable=()
while IFS= read -r -d '' project; do
    rel=${project#"$ROOT"}
    rel=${rel#/}
    if grep -qE '<IsPackable>\s*false\s*</IsPackable>' "$project"; then
        continue
    fi
    packable+=("$rel")
done < <(find "$ROOT" -name '*.csproj' -type f \
    -not -path '*/node_modules/*' \
    -not -path '*/.git/*' \
    -not -path '*/Library/*' \
    -not -path '*/obj/*' \
    -not -path '*/bin/*' \
    -not -path '*~/*' \
    -print0)

if [ ${#packable[@]} -eq 0 ]; then
    echo "Error: no packable .csproj in the repository — the nuget channel has nothing to pack" >&2
    exit 1
fi

if [ ${#packable[@]} -eq 1 ]; then
    printf '%s\n' "${packable[0]}"
    exit 0
fi

# More than one: a solution at the root packs all of them in one command. The
# shallowest, then the first by path, so the answer does not depend on the filesystem.
best=""
best_key=""
while IFS= read -r -d '' solution; do
    rel=${solution#"$ROOT"}
    rel=${rel#/}
    slashes=${rel//[!\/]/}
    key=$(printf '%03d|%s' "${#slashes}" "$rel")
    if [ -z "$best_key" ] || [[ $key < $best_key ]]; then
        best_key=$key
        best=$rel
    fi
done < <(find "$ROOT" -maxdepth 2 -name '*.sln' -type f \
    -not -path '*/obj/*' -not -path '*/bin/*' -print0)

if [ -n "$best" ]; then
    printf '%s\n' "$best"
    exit 0
fi

echo "Error: ${#packable[@]} packable projects and no solution to pack them together; name nuget-project" >&2
printf '  %s\n' "${packable[@]}" >&2
exit 1
