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


# Rule names the repository has decided are wrong, separated by commas, from
# `INSPECT_IGNORE_RULES`. A rule can exist in the analyser and not in the IDE the
# team uses — the Unity plugin gained a "Unity serialized field" naming rule in a
# 2026.2 patch build, so a runner with that build reports a convention that the
# team's Rider cannot even display, and nobody can reproduce or silence it where
# the code is written. Naming the rule is the honest fix: the finding is dropped
# on purpose, and the log says how many were dropped, so this reads as a decision
# and not as the analysis silently doing less.
IGNORE_RULES_ENV = "INSPECT_IGNORE_RULES"


def ignored_rules() -> Set[str]:
    """The rule names to drop, lower-cased. Empty when nothing is configured."""
    raw = os.environ.get(IGNORE_RULES_ENV, "")
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


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


# A repository can carry ReSharper settings of its own. `jb inspectcode` reads
# `<solution>.DotSettings` automatically, but the solution it is pointed at is not
# always the repository's own: for a Unity package it is the project Unity
# generates in the PR's working directory, and a file next to the package is miles
# away from it. Passing the file explicitly is what makes the repository's settings
# apply either way. First one wins; the files are settings, not a search space.
def repo_settings(workdir: str) -> Optional[str]:
    """The repository's own ReSharper settings file, or None."""
    try:
        for path in sorted(Path(workdir).rglob("*.DotSettings")):
            if path.is_file():
                return str(path)
    except OSError as exc:
        log(f"Could not look for .DotSettings files in {workdir}: {exc}")
    return None


def run_inspectcode(
    target: str,
    workdir: str,
    report: Path,
    timeout: int = 1200,
    projects: Sequence[str] = (),
) -> bool:
    """Run ``jb inspectcode`` over ``target``, writing ``report``.

    ``projects`` names the projects inside ``target`` to report on, when
    ``target`` is a solution. Everything else in the solution is still *loaded* —
    which is the point: a project inspected on its own resolves its references
    from their build outputs, and those do not exist unless something built them
    in the shape inspectcode expects. Pointed at the solution, the referenced
    project is loaded as source and the reference resolves no matter what was
    compiled. ``--project`` keeps the findings to the code under review, so the
    rest of the solution costs project loading and nothing else.

    Returns whether a report was actually produced. The report path is per
    solution and inside the PR's own directory, so two reviews running at the
    same time cannot overwrite each other's results.
    """
    binary = inspectcode_binary()
    if not binary:
        return False
    cmd = [binary, "inspectcode", target, f"--output={report}", "--format=Xml", *inspect_args()]
    for name in projects:
        cmd.append(f"--project={name}")
    settings = repo_settings(workdir)
    if settings:
        cmd.append(f"--settings={settings}")
        log(f"ReSharper: using the repository's settings from {Path(settings).name}.")

    log(f"Running ReSharper inspectcode on {Path(target).name} ...")
    if projects:
        log(
            f"ReSharper: {Path(target).name} is inspected for {_sample(list(projects))} "
            "only; the rest of the solution is loaded so their references resolve."
        )
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


# Unity compiles without nullable reference types: every project the editor
# generates has `<Nullable>` off, and object lifetimes are the engine's rather than
# the CLR's — a destroyed `UnityEngine.Object` compares equal to null while being a
# live reference, and code is written for that. An inspection whose verdict comes
# from nullability annotations is therefore reasoning about a contract the project
# does not have.
#
# AccessKing PR #3 is what that costs: `o?.GetHashCode() ?? 0` in an equality
# comparer was reported twice on one line — `ConstantConditionalAccessQualifier` and
# `ConstantNullCoalescingCondition` — while the author's Rider, whose Unity project
# model resolves Unity's own reference assemblies, reported neither. The ids are
# matched by prefix because ReSharper ships suffixed variants
# (`…AccordingToNullableAPIContract`).
UNITY_NULLABLE_INSPECTIONS = (
    "ConstantConditionalAccessQualifier",
    "ConstantNullCoalescingCondition",
    "ConditionIsAlwaysTrueOrFalse",
    "PossibleNullReferenceException",
    "AssignNullToNotNullAttribute",
    "AnnotationRedundancyInHierarchy",
    "RedundantNullnessAttributeWithNullableReferenceTypes",
    "NullableWarningSuppressionIsUsed",
)


def is_nullable_inspection(type_id: str) -> bool:
    """Is this finding a verdict about nullability?"""
    return any(
        (type_id or "").startswith(prefix) for prefix in UNITY_NULLABLE_INSPECTIONS
    )


def drop_nullable_issues(
    issues: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Split out the nullability findings a Unity project cannot honour."""
    kept: List[Dict[str, Any]] = []
    dropped: Dict[str, int] = {}
    for issue in issues:
        type_id = issue.get("type") or ""
        if is_nullable_inspection(type_id):
            dropped[type_id] = dropped.get(type_id, 0) + 1
        else:
            kept.append(issue)
    return kept, dropped


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
                "rule": rule_name(issue.get("Message") or ""),
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
#
# The sentence is English because it cannot be anything else: the global tool
# ships resource folders for thirteen languages, and every one of them holds only
# Microsoft's satellite assemblies — no JetBrains ones — so its own messages are
# untranslated whatever the machine's locale says. The `TypeId` above is the part
# that is guaranteed language-independent, and it is the gate: if JetBrains ever
# does translate this text, the match stops and the finding keeps the plain
# comment it would have had anyway.
_SUGGESTED_NAME = re.compile(
    r"Name '(?P<current>[^']+)' does not match rule '[^']*'\.\s*"
    r"Suggested name is '(?P<suggested>[^']+)'\."
)


# `... does not match rule 'Unity serialized field'. ...` — the rule's own name,
# as ReSharper prints it, for the ignore list.
_RULE_NAME = re.compile(r"does not match rule '(?P<rule>[^']*)'")


def rule_name(message: str) -> str:
    """The naming rule a finding was raised by, or "" when it names none."""
    match = _RULE_NAME.search(message or "")
    return match.group("rule") if match else ""


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


def _is_compiler_warning(issue: Dict[str, Any]) -> bool:
    """A diagnostic the C# compiler itself would have produced."""
    return "CSharpWarnings" in (issue.get("type") or "")


def filter_to_changes(
    issues: List[Dict[str, Any]],
    changed_lines: Dict[str, Set[int]],
) -> List[Dict[str, Any]]:
    """Keep only reportable-severity issues on lines the PR changed.

    Compiler *warnings* are dropped from any file where the report also carried a
    resolve error. A compilation that did not resolve produces diagnostics about
    that failure rather than about the code — the measured shape: with the base
    assembly missing, a `protected override` cannot bind, so it reads as a *new*
    member and ReSharper reports CS0628 ("declaring new protected method ... in a
    sealed class") on every override in the class. The resolve errors themselves
    are dropped here as build-environment noise (see ``_is_noise``), which used to
    leave only the warning they caused — noise wearing a warning's clothes.
    """
    unresolved = {i["file"] for i in issues if _is_noise(i)}
    if unresolved:
        # Silence here is the dangerous kind: an unresolved reference makes the
        # analyser describe its own broken view instead of the code, and the
        # findings that would say so are exactly the ones dropped as noise. Name
        # the files, so a run that analysed a partial graph is visibly partial.
        log(
            "ReSharper: references did not resolve in "
            + _sample(sorted(unresolved))
            + " — diagnostics from that are ignored."
        )
    out: List[Dict[str, Any]] = []
    suppressed = 0
    for issue in issues:
        if issue["severity"] not in REPORTED_SEVERITIES:
            continue
        if _is_noise(issue):
            continue
        if issue["file"] in unresolved and _is_compiler_warning(issue):
            suppressed += 1
            continue
        lines = changed_lines.get(issue["file"])
        if not lines or issue["line"] not in lines:
            continue
        out.append(issue)
    if suppressed:
        # Say it out loud: the alternative is an analysis that quietly reports
        # less, which is the failure this pipeline is built to avoid.
        log(
            f"ReSharper: {suppressed} compiler warning(s) dropped — their file did "
            "not resolve, so the warning describes the failed resolution."
        )
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
    ``inspected`` holds the targets that produced a report, so a caller can tell
    which half of a two-solution analysis actually happened.
    """

    issues: List[Dict[str, Any]] = field(default_factory=list)
    all_issues: List[Dict[str, Any]] = field(default_factory=list)
    targets: List[str] = field(default_factory=list)
    inspected: List[str] = field(default_factory=list)
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
    projects: Optional[Dict[str, Sequence[str]]] = None,
    unity: bool = False,
) -> Analysis:
    """Run ReSharper over every target and return the issues on changed lines.

    ``targets`` are the solutions to inspect — the repository's own and/or the
    Unity-generated one. An empty list means there is nothing to analyse, which
    the result distinguishes from an inspection that produced no report.
    ``projects`` maps a target to the projects inside it that the findings should
    be limited to; a target with no entry is inspected whole. ``unity`` says the
    code under analysis is a Unity project, whose findings are filtered for
    nullability — see :data:`UNITY_NULLABLE_INSPECTIONS`.
    Never raises: static analysis is best-effort and must not break the review.
    """
    targets = list(targets)
    projects = dict(projects or {})
    try:
        if not workdir or not targets:
            log("No solution to inspect; skipping static analysis.")
            return Analysis(targets=targets)
        report_dir = report_dir or Path(workdir)

        collected: List[Dict[str, Any]] = []
        reports = 0
        inspected: List[str] = []
        for index, target in enumerate(targets, start=1):
            report = report_dir / f"resharper-{index}.xml"
            if report.exists():
                report.unlink()
            wanted = projects.get(target) or ()
            if not run_inspectcode(target, workdir, report, projects=wanted):
                if not wanted:
                    continue
                # A filter that matches nothing produces no report at all — it
                # must not read as "nothing to report". The whole solution is
                # still the correct analysis, only a wider one, so fall back to
                # it rather than losing the step.
                log(
                    "ReSharper: none of " + _sample(list(wanted)) + " matched a project in "
                    + f"{Path(target).name}; inspecting it whole instead."
                )
                if report.exists():
                    report.unlink()
                if not run_inspectcode(target, workdir, report):
                    continue
            reports += 1
            inspected.append(target)
            issues = parse_report(str(report))
            for issue in issues:
                issue["file"] = relative_to_clone(issue["file"], target, workdir)
            log(f"ReSharper: {Path(target).name}: {len(issues)} issue(s).")
            collected.extend(issues)

        issues = _dedupe(collected)
        if unity:
            issues, nullable_dropped = drop_nullable_issues(issues)
            if nullable_dropped:
                detail = ", ".join(
                    f"{name} ×{count}" for name, count in sorted(nullable_dropped.items())
                )
                log(
                    f"ReSharper: {sum(nullable_dropped.values())} nullability "
                    f"finding(s) dropped ({detail}) — a Unity project compiles "
                    "without nullable reference types, so the annotation the "
                    "inspection reasons from is not a contract this code has."
                )
        duplicates = len(collected) - len(issues)
        if duplicates:
            log(f"ReSharper: {duplicates} duplicate finding(s) merged.")

        ignored = ignored_rules()
        if ignored:
            kept_by_rule = [i for i in issues if (i.get("rule") or "").lower() not in ignored]
            dropped = len(issues) - len(kept_by_rule)
            if dropped:
                log(
                    f"ReSharper: {dropped} finding(s) ignored by rule name "
                    f"({', '.join(sorted(ignored))})."
                )
            issues = kept_by_rule

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
            inspected=inspected,
            reports=reports,
            duplicates=duplicates,
        )
    except Exception as exc:  # noqa: BLE001 - never break the review
        log(f"Static analysis failed, continuing without it: {exc}")
        return Analysis(targets=targets)
