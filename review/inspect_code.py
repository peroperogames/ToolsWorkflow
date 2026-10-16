"""ReSharper (JetBrains `jb inspectcode`) static analysis integration.

The runner has the ReSharper global tool installed, which reads the repository's
own `.editorconfig` and project settings. This gives deterministic, project-
specific findings (naming, style, redundancies, correctness inspections) that
are far more reliable than asking the model to guess a convention.

The flow: run `jb inspectcode` over each solution the repository has, parse the
XML reports, keep only issues on lines the pull request actually changed, and
merge the solutions back into one list. A repository can legitimately have two —
a hand-maintained solution that contains a SourceGenerator, say, and the solution
Unity generates for the package it also ships — and they see different code, so
both are inspected and their findings de-duplicated.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import subproc
import tool_path

# Severity as reported by ReSharper -> whether we surface it. WARNING and above
# are worth a comment; SUGGESTION/HINT are too noisy to post on every PR.
REPORTED_SEVERITIES = {"ERROR", "WARNING"}

# Compiler/resolve errors are dropped. Unity packages reference UnityEngine via
# DLLs the runner may not have on the exact path, which turns every reference
# into a "cannot resolve" error. Those are build-environment noise, not review
# findings — compilation itself is a separate CI concern.
IGNORED_TYPE_SUBSTRINGS = ("CSharpErrors",)
IGNORED_MESSAGE_SUBSTRINGS = (
    "cannot resolve symbol",
    "could not be resolved",
    "could not be found",
    "unknown type",
    "is not supported in this version",
)

# inspectcode builds the solution before inspecting it, through an MSBuild it
# picks itself — and it picks the newest .NET SDK it can find. When that newest
# SDK is a preview or a half-installed one, the build fails before any report is
# written. Pinning a known-good SDK is the fix, so a failure that looks like this
# says so instead of leaving a bare exit code.
SDK_TROUBLE_MARKERS = (
    "MSB4236",
    "MSB4276",
    "NETSDK1045",
    "could not resolve sdk",
    "does not support targeting",
)


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


# Where `jb` ends up when it is not on PATH: it is a .NET global tool, so its own
# installer puts it in ~/.dotnet/tools. Same story as the Unity CLI — a login
# shell has that on its PATH and a runner's service process usually does not, so
# the tool is installed, working from a terminal, and invisible to a job.
JB_FALLBACK_DIRS = ("~/.dotnet/tools", "~/.local/bin", "/usr/local/bin")

_JB: Optional[str] = None
_JB_RESOLVED = False


def inspectcode_binary() -> Optional[str]:
    """The ``jb`` executable, or None when it is not installed.

    Resolved once per run and reported once, as a fact rather than a warning.
    """
    global _JB, _JB_RESOLVED
    if not _JB_RESOLVED:
        _JB = _resolve_inspectcode()
        _JB_RESOLVED = True
    return _JB


def _resolve_inspectcode() -> Optional[str]:
    return tool_path.find(
        "jb",
        JB_FALLBACK_DIRS,
        override_env="INSPECT_JB",
        label="ReSharper CLI",
        hint=(
            "Install it for the user the runner runs as — `dotnet tool install -g "
            "JetBrains.ReSharper.GlobalTools` — and make sure that user's PATH has "
            "it. There is no static analysis without it."
        ),
    )


def inspect_args() -> List[str]:
    """Extra ``jb inspectcode`` arguments taken from the environment.

    By default inspectcode is told **not** to build the solution it inspects.
    The pipeline has already compiled the code — Unity for a package, the .NET
    SDK for a C# project — and letting inspectcode build it again is both
    redundant and demonstrably fragile: Unity's generated projects are written
    for Unity's own compiler settings, and a generic MSBuild run trips over them
    (obsolete-API warnings promoted to errors, output paths it cannot open). A
    failed build means **no report at all**, which is indistinguishable from
    "no findings". inspectcode still evaluates MSBuild to get the project model
    and the set of files to inspect; it just does not compile first.

    Set ``INSPECT_BUILD`` to let it build after all — needed only if the
    solution's real sources are produced by a build (a source generator that
    emits files nothing else writes), which is why the properties below still
    turn warnings-as-errors off when they apply.

    ``INSPECT_DOTNET_SDK`` pins the SDK whose MSBuild it uses
    (``--dotnetcoresdk=10.0.300``) instead of letting the newest installed one
    win, which fails on a broken preview.
    """
    args: List[str] = []
    sdk = os.environ.get("INSPECT_DOTNET_SDK", "").strip()
    if sdk:
        args.append(f"--dotnetcoresdk={sdk}")
    if not _env_bool("INSPECT_BUILD"):
        args.append("--no-build")
    return args + [
        "--properties:TreatWarningsAsErrors=false",
        "--properties:MSBuildTreatWarningsAsErrors=false",
    ]


def log(message: str) -> None:
    print(message, file=sys.stderr)


def _sample(paths: Sequence[str], limit: int = 6) -> str:
    """A few names and a count, so a long list stays one readable line."""
    names = [Path(p).name or "?" for p in paths]
    if not names:
        return "(none)"
    shown = ", ".join(names[:limit])
    return shown if len(names) <= limit else f"{shown} (+{len(names) - limit} more)"


def run_inspectcode(target: str, workdir: str, report: Path, timeout: int = 1200) -> bool:
    """Run ``jb inspectcode`` over ``target``, writing ``report``.

    Returns whether a report was actually produced. The report path is per
    solution and inside the PR's own directory, so two reviews running at the
    same time cannot overwrite each other's results.
    """
    binary = inspectcode_binary()
    if not binary:
        return False
    cmd = [binary, "inspectcode", target, f"--output={report}", "--format=Xml", *inspect_args()]

    log(f"Running ReSharper inspectcode on {Path(target).name} ...")
    try:
        rc, output = subproc.run(cmd, timeout, cwd=workdir)
    except FileNotFoundError:
        log(f"ReSharper CLI at {binary} could not be executed; skipping static analysis.")
        return False
    except subprocess.TimeoutExpired:
        log(f"inspectcode timed out after {timeout}s; skipping static analysis.")
        return False

    if rc != 0:
        log(f"inspectcode exited {rc}: {output.strip()[-500:]}")
        # A report may still have been written; fall through and try to parse it.
    if not report.exists():
        log(f"inspectcode produced no report for {Path(target).name}.")
        if any(marker in output.lower() for marker in (m.lower() for m in SDK_TROUBLE_MARKERS)):
            log(
                "hint: inspectcode could not resolve a usable .NET SDK for its build. "
                "Set INSPECT_DOTNET_SDK to an installed version (e.g. 10.0.300) so it "
                "uses that one instead of auto-detecting."
            )
        return False
    return True


def parse_report(report_path: str) -> List[Dict[str, Any]]:
    """Parse a ReSharper XML report into issue dicts.

    Each issue: ``{file, line, severity, message, type, rename}``. ``file`` is
    exactly what the report says — a path relative to the *solution*, per
    JetBrains' format — and the caller normalizes it with
    :func:`relative_to_clone`. ``rename`` is the fix the naming inspection asks
    for, when it asks for one; see :func:`suggested_rename`.
    """
    try:
        tree = ET.parse(report_path)
    except (ET.ParseError, OSError) as exc:
        log(f"Could not parse inspectcode report: {exc}")
        return []

    root = tree.getroot()

    # Severity lives on the issue-type definitions, keyed by type id.
    severity_by_type: Dict[str, str] = {}
    for it in root.iter("IssueType"):
        type_id = it.get("Id")
        severity = (it.get("Severity") or "").upper()
        if type_id:
            severity_by_type[type_id] = severity

    issues: List[Dict[str, Any]] = []
    for issue in root.iter("Issue"):
        type_id = issue.get("TypeId") or ""
        severity = (issue.get("Severity") or severity_by_type.get(type_id, "")).upper()
        file_attr = issue.get("File")
        line_attr = issue.get("Line")
        if not file_attr or not line_attr:
            continue
        try:
            line = int(line_attr)
        except ValueError:
            continue
        issues.append(
            {
                "file": file_attr.replace("\\", "/"),
                "line": line,
                "severity": severity,
                "message": issue.get("Message") or "",
                "type": type_id,
                "rename": suggested_rename(type_id, issue.get("Message") or ""),
            }
        )
    return issues


# ReSharper's naming inspection is the one that says what it wants instead, and
# it says it in prose — the report carries no structured fix, only the message
# and the offset of the offending name:
#
#   <Issue TypeId="InconsistentNaming" File="Demo.cs" Offset="133-150" Line="5"
#          Message="Name 'wrongMethodFormat' does not match rule 'Methods'.
#                   Suggested name is 'WrongMethodFormat'." />
#
# So this reads a sentence and nothing more, and the caller treats it as one: it
# only becomes a suggested edit when the rename cannot mean anything else.
_SUGGESTED_NAME = re.compile(
    r"Name '(?P<current>[^']+)' does not match rule '[^']*'\.\s*"
    r"Suggested name is '(?P<suggested>[^']+)'\."
)


def suggested_rename(type_id: str, message: str) -> Optional[Tuple[str, str]]:
    """``(current, suggested)`` when the finding names the rename it wants."""
    if type_id != "InconsistentNaming":
        return None
    match = _SUGGESTED_NAME.search(message or "")
    if not match:
        return None
    current = match.group("current").strip()
    suggested = match.group("suggested").strip()
    if not current or not suggested or current == suggested:
        return None
    return current, suggested


def relative_to_clone(file_value: str, target: str, workdir: str) -> str:
    """Turn a report path into one relative to the clone root.

    The report spells paths relative to the solution (JetBrains documents it that
    way; ``--absolute-paths`` is the opt-in for the other form), while the changed
    lines arrive as paths relative to the repository. Resolving against the
    solution's directory and re-relativizing against the clone is what makes the
    two comparable — without it every finding looks like it belongs to a file the
    pull request never touched, and all of them are dropped.

    A path that lands outside the clone (Unity's own packages, build output) is
    returned unchanged: it can never match a pull-request file, which is the
    right outcome for it.
    """
    path = Path(file_value)
    if not path.is_absolute():
        path = Path(target).parent / file_value
    try:
        return path.resolve().relative_to(Path(workdir).resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


def _is_noise(issue: Dict[str, Any]) -> bool:
    """Drop compiler/resolve errors caused by a missing build environment."""
    type_id = issue.get("type") or ""
    if any(sub in type_id for sub in IGNORED_TYPE_SUBSTRINGS):
        return True
    message = (issue.get("message") or "").lower()
    return any(sub in message for sub in IGNORED_MESSAGE_SUBSTRINGS)


def filter_to_changes(
    issues: List[Dict[str, Any]],
    changed_lines: Dict[str, Set[int]],
) -> List[Dict[str, Any]]:
    """Keep only reportable-severity issues on lines the PR changed."""
    out: List[Dict[str, Any]] = []
    for issue in issues:
        if issue["severity"] not in REPORTED_SEVERITIES:
            continue
        if _is_noise(issue):
            continue
        lines = changed_lines.get(issue["file"])
        if not lines or issue["line"] not in lines:
            continue
        out.append(issue)
    return out


def _dedupe(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One entry per distinct finding, across every solution inspected.

    Two solutions of the same repository share most of their sources, so the same
    issue is reported by both; posting it twice would just be noise.
    """
    seen: Set[tuple] = set()
    out: List[Dict[str, Any]] = []
    for issue in issues:
        key = (issue["file"], issue["line"], issue["type"], issue["message"])
        if key in seen:
            continue
        seen.add(key)
        out.append(issue)
    return out


@dataclass
class Analysis:
    """Outcome of a ReSharper pass.

    Kept apart from the issue list so a caller can tell "inspected, found
    nothing" from "never ran" — those look identical in a bare list, and the
    second one silently cost the pull request its static analysis.

    ``issues`` is what to post: the findings on the lines the pull request wrote.
    ``all_issues`` is everything the inspection reported, including the parts of
    the file it is not going to be asked about — which is where the caller looks
    to find out whether a name it wants to rename is *declared* somewhere else.
    """

    issues: List[Dict[str, Any]] = field(default_factory=list)
    all_issues: List[Dict[str, Any]] = field(default_factory=list)
    targets: List[str] = field(default_factory=list)
    reports: int = 0
    duplicates: int = 0

    @property
    def ran(self) -> bool:
        """Did at least one solution actually get inspected?"""
        return self.reports > 0


def analyze(
    workdir: str,
    changed_lines: Dict[str, Set[int]],
    targets: Sequence[str],
    report_dir: Optional[Path] = None,
) -> Analysis:
    """Run ReSharper over every target and return the issues on changed lines.

    ``targets`` are the solutions to inspect — the repository's own and/or the
    Unity-generated one. An empty list means there is nothing to analyse, which
    the result distinguishes from an inspection that produced no report.
    Never raises: static analysis is best-effort and must not break the review.
    """
    targets = list(targets)
    try:
        if not workdir or not targets:
            log("No solution to inspect; skipping static analysis.")
            return Analysis(targets=targets)
        report_dir = report_dir or Path(workdir)

        collected: List[Dict[str, Any]] = []
        reports = 0
        for index, target in enumerate(targets, start=1):
            report = report_dir / f"resharper-{index}.xml"
            if report.exists():
                report.unlink()
            if not run_inspectcode(target, workdir, report):
                continue
            reports += 1
            issues = parse_report(str(report))
            for issue in issues:
                issue["file"] = relative_to_clone(issue["file"], target, workdir)
            log(f"ReSharper: {Path(target).name}: {len(issues)} issue(s).")
            collected.extend(issues)

        issues = _dedupe(collected)
        duplicates = len(collected) - len(issues)
        if duplicates:
            log(f"ReSharper: {duplicates} duplicate finding(s) merged.")
        kept = filter_to_changes(issues, changed_lines)
        log(f"ReSharper: {len(issues)} issue(s) total, {len(kept)} on changed lines.")
        if issues and not kept:
            # Nothing landed on a changed line. Usually that is ordinary — the
            # pull request touched a file the findings are not in — and it is
            # also what a path mismatch looks like, where the report's paths
            # never line up with the diff's and no finding can ever be posted.
            # The two are indistinguishable from the count alone, so say where
            # each side actually was.
            log(
                "ReSharper: findings are in "
                + _sample(sorted({str(i.get("file") or "?") for i in issues}))
                + "; changed lines are in "
                + _sample(sorted(changed_lines))
            )
        return Analysis(
            issues=kept,
            all_issues=issues,
            targets=targets,
            reports=reports,
            duplicates=duplicates,
        )
    except Exception as exc:  # noqa: BLE001 - never break the review
        log(f"Static analysis failed, continuing without it: {exc}")
        return Analysis(targets=targets)
