"""What kind of repository is under review.

The pipeline routes on this classification. A UPM package is compiled and tested
in a per-PR Unity project; a repository that ships its own C# solution is built
and tested with the .NET SDK instead; and ReSharper runs against whichever
solutions exist — the Unity-generated one for a package, the repository's own one
for a C# project, and both for a repository that is a C# project containing a UPM
package as well (a SourceGenerator, say). Repositories in any other language get
the AI review and nothing else.

Every answer comes from the cloned pull-request head, so classifying costs
nothing beyond the clone the pipeline already needs, and no extra API calls are
made to guess at it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Tuple

KIND_CSHARP = "csharp"  # ships its own solution/project, but is not a UPM package
KIND_UNITY = "unity"  # a UPM package
KIND_MIXED = "mixed"  # a UPM package inside a C# project that has its own solution
KIND_OTHER = "other"  # neither: another language

# Directories that never hold the repository's own sources: build output, package
# caches, VCS data. Walking them finds package.json / csproj files that belong to
# something else, which would misclassify the repository.
SKIP_DIRS = {
    ".git",
    ".ai-review",
    "node_modules",
    "Library",
    "Temp",
    "obj",
    "bin",
    "Logs",
    "PackageCache",
    ".vs",
    ".idea",
}

# A solution a repository maintains by hand lives here, and is the one meant to
# be built and opened outside Unity — so it is the one ReSharper should use.
PREFERRED_SOLUTION_DIR = "Projects~"

# Both solution formats count. The .NET SDK has defaulted to the XML `.slnx`
# since .NET 10, so a recently scaffolded repository ships one and would
# otherwise look like it had no solution at all.
SOLUTION_SUFFIXES = (".sln", ".slnx")


def walk_files(root: Path, match: Callable[[Path], bool]) -> Iterator[Path]:
    """Files under ``root`` that ``match``, skipping the noise directories."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if match(path):
                yield path


def _depth(path: Path, root: Path) -> int:
    return len(path.relative_to(root).parts)


def find_package(clone_dir: str) -> Tuple[str, str]:
    """``(name, root)`` of the UPM package in the clone, or ``("", "")``.

    The shallowest ``package.json`` that carries a name wins, so a repository
    that holds its package at the root is not mistaken for one that nests a
    sample project deeper down.
    """
    root = Path(clone_dir)
    found: List[Tuple[int, str, str]] = []
    for manifest in walk_files(root, lambda p: p.name == "package.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        name = (data.get("name") or "").strip()
        if name:
            found.append((_depth(manifest, root), name, str(manifest.parent)))
    if not found:
        return "", ""
    _depth_value, name, package_root = min(found, key=lambda f: (f[0], f[2]))
    return name, package_root


def find_solutions(clone_dir: str) -> List[str]:
    """Every solution/project the repository ships, best candidate first.

    A hand-maintained ``Projects~`` solution wins over anything else, then any
    other solution — a classic ``.sln`` ahead of an XML ``.slnx`` when it has
    both — and finally a bare project file, for repositories that only have one.
    An explicit ``INSPECT_TARGET`` (relative to the clone root) replaces the
    discovery entirely.
    """
    override = os.environ.get("INSPECT_TARGET", "").strip()
    root = Path(clone_dir)
    if override:
        candidate = root / override
        return [str(candidate if candidate.exists() else override)]

    solutions = list(walk_files(root, lambda p: p.suffix.lower() in SOLUTION_SUFFIXES))
    solutions.sort(key=lambda p: (0 if p.suffix.lower() == ".sln" else 1, str(p)))
    preferred = [s for s in solutions if PREFERRED_SOLUTION_DIR in s.parts]
    ordered = preferred + [s for s in solutions if s not in preferred]
    if ordered:
        return [str(s) for s in ordered]
    return [str(p) for p in sorted(walk_files(root, lambda p: p.suffix.lower() == ".csproj"), key=str)]


@dataclass(frozen=True)
class Kind:
    """What the clone turned out to be."""

    name: str
    package_name: str = ""
    package_root: str = ""
    solution: str = ""

    @property
    def is_package(self) -> bool:
        return bool(self.package_name)

    @property
    def has_solution(self) -> bool:
        return bool(self.solution)

    def to_dict(self) -> dict:
        """Plain data, so a classification can outlive the process that made it."""
        return {
            "name": self.name,
            "package_name": self.package_name,
            "package_root": self.package_root,
            "solution": self.solution,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Kind":
        return cls(
            name=str(data.get("name") or ""),
            package_name=str(data.get("package_name") or ""),
            package_root=str(data.get("package_root") or ""),
            solution=str(data.get("solution") or ""),
        )

    def describe(self) -> str:
        if self.name == KIND_UNITY:
            return f"Unity package {self.package_name}"
        if self.name == KIND_MIXED:
            return (
                f"Unity package {self.package_name} in a C# project "
                f"({Path(self.solution).name})"
            )
        if self.name == KIND_CSHARP:
            return f"C# project ({Path(self.solution).name})"
        return "no C# or Unity content"


def detect(clone_dir: str) -> Kind:
    """Classify the cloned pull-request head."""
    package_name, package_root = find_package(clone_dir)
    solutions = find_solutions(clone_dir)
    solution = solutions[0] if solutions else ""

    if package_name and solution:
        kind = KIND_MIXED
    elif package_name:
        kind = KIND_UNITY
    elif solution:
        kind = KIND_CSHARP
    else:
        kind = KIND_OTHER
    return Kind(kind, package_name, package_root, solution)
