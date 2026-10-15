"""Finding the external tools the pipeline needs.

Nothing here is configured with a path. Where a tool lives on a particular
machine is not something the caller of this workflow knows, so each tool is
looked for instead: ``PATH`` first, then the directories these tools install
themselves into. Those directories are in the list because of one specific gap —
``dotnet tool install -g`` writes to ``~/.dotnet/tools``, and a runner started by
``run.sh`` or a service unit inherits a minimal ``PATH``, so a tool that works
when typed by hand is invisible to a job.

Two failures look identical from the outside, and telling them apart is most of
what this module is for:

* the tool is not installed for the runner's user, and
* the tool is installed for *another* user — under ``/root``, say — which a
  service account cannot even traverse.

The second is what a runner whose tools were installed as root looks like, and
``shutil.which`` reports it exactly the way it reports the first: nothing. So a
miss also checks whether anything on the search path exists but is out of reach,
and says so, because "install it" is the wrong advice when it is already there.
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import List, Optional, Sequence, Set


def log(message: str) -> None:
    print(message, file=sys.stderr)


def _names(name: str) -> Sequence[str]:
    return (f"{name}.exe", name) if os.name == "nt" else (name,)


def _search_dirs(fallback_dirs: Sequence[str]) -> List[str]:
    """Every directory that gets looked at, in the order it gets looked at."""
    ordered: List[str] = []
    seen: Set[str] = set()
    for directory in (*fallback_dirs, *os.environ.get("PATH", "").split(os.pathsep)):
        if not directory:
            continue
        expanded = os.path.normpath(os.path.expanduser(directory))
        if expanded not in seen:
            seen.add(expanded)
            ordered.append(expanded)
    return ordered


def _out_of_reach(name: str, fallback_dirs: Sequence[str]) -> List[str]:
    """Places the tool might be but this user cannot use.

    Only reported for a tool that could not be found: an unreadable directory on
    ``PATH`` is otherwise just noise.
    """
    notes: List[str] = []
    for directory in _search_dirs(fallback_dirs):
        try:
            os.stat(directory)
        except PermissionError:
            notes.append(f"{directory} cannot be read by this user")
            continue
        except OSError:
            continue
        for candidate_name in _names(name):
            candidate = os.path.join(directory, candidate_name)
            if os.path.isfile(candidate) and not os.access(candidate, os.X_OK):
                notes.append(f"{candidate} exists but is not executable by this user")
    return notes


def find(
    name: str,
    fallback_dirs: Sequence[str] = (),
    override_env: str = "",
    label: str = "",
    hint: str = "",
) -> Optional[str]:
    """The executable for ``name``, or None when this user cannot reach one.

    Which one was used is logged once, as a fact rather than a warning: a build
    that behaves differently here than it does by hand starts with the answer to
    "which one ran".
    """
    label = label or name

    override = os.environ.get(override_env, "").strip() if override_env else ""
    if override:
        found = shutil.which(override) or (override if os.path.exists(override) else None)
        if found:
            log(f"{label}: {found}")
            return found
        log(f"{override_env} set but not found: {override}")
        return None

    found = shutil.which(name)
    if found:
        log(f"{label}: {found}")
        return found

    tried: List[str] = []
    for directory in fallback_dirs:
        for candidate_name in _names(name):
            candidate = os.path.normpath(
                os.path.join(os.path.expanduser(directory), candidate_name)
            )
            tried.append(candidate)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                log(f"{label}: {candidate} (in {directory}; not on PATH here)")
                return candidate

    where = "Checked PATH" + (f" and: {', '.join(tried)}" if tried else "") + "."
    notes = _out_of_reach(name, fallback_dirs)
    also = " Also: " + "; ".join(notes) + "." if notes else ""
    log(f"{label} ('{name}') was not found. {where}{also} {hint}".rstrip())
    return None
