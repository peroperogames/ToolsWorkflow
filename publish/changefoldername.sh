#!/bin/bash
# Rename the folders a package's own file: dependencies point at.
#
# A UPM package that ships other UPM packages as `file:../Foo~` dependencies needs
# its `Foo/` folder to be called `Foo~` in the published tarball, or the installed
# package resolves the dependency to a path that is not there. This step renames
# exactly those folders, and deletes the `.meta` that belonged to the old name so
# Unity does not see an orphan.
#
# Output is English, like every other step: the Chinese lines this script used to
# print were the only ones left in the log, and read as another tool's output.
set -euo pipefail

root="${CI_PROJECT_DIR:?CI_PROJECT_DIR is not set}"
manifest="$root/package.json"

if [ ! -f "$manifest" ]; then
  echo "No package.json at $manifest; nothing to rename."
  exit 0
fi

echo "Folders in the package:"
find "$root" -maxdepth 1 -mindepth 1 -type d -printf '  %f\n' | sort

# The folder names the manifest points at: every string ending in `X~`, which is how
# a package references a folder that has to carry the tilde once published.
python="${PYTHON:-$(command -v python3 || command -v python || true)}"
if [ -z "$python" ]; then
  echo "::error::renaming folders needs python3 (to read package.json); none on PATH." >&2
  exit 1
fi

# Collected into a variable first: a here-document inside a process substitution is
# consumed by the wrong command, and the names come back empty.
names=$("$python" - "$manifest" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8-sig") as handle:
    data = json.load(handle)

found = set()


def walk(node):
    if isinstance(node, dict):
        for value in node.values():
            walk(value)
    elif isinstance(node, list):
        for value in node:
            walk(value)
    elif isinstance(node, str):
        match = re.search(r"([^/\\~]+)~\s*$", node)
        if match:
            found.add(match.group(1))


walk(data)
for name in sorted(found):
    print(name)
PY
)
mapfile -t wanted <<< "$names"
# A manifest with no such folder yields an empty line rather than no line.
wanted=($(printf '%s\n' "${wanted[@]}" | sed '/^$/d'))

if [ ${#wanted[@]} -eq 0 ]; then
  echo "No folder referenced with '~' in package.json; nothing to rename."
else
  echo "Folders package.json references with '~': ${wanted[*]}"
fi

renamed=0
for name in "${wanted[@]}"; do
  source="$root/$name"
  if [ ! -d "$source" ]; then
    echo "  $name: no such folder; skipped."
    continue
  fi
  if [ -e "${source}~" ]; then
    echo "  $name: ${name}~ already exists; skipped."
    continue
  fi
  mv "$source" "${source}~"
  echo "  $name -> ${name}~"
  if [ -f "$root/$name.meta" ]; then
    rm -f "$root/$name.meta"
    echo "  removed $name.meta, which named the old folder"
  fi
  renamed=$((renamed + 1))
done

echo "Renamed $renamed folder(s)."
echo "Folders after the rename:"
find "$root" -maxdepth 1 -mindepth 1 -type d -printf '  %f\n' | sort
