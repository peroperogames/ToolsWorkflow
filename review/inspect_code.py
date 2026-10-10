"""ReSharper (JetBrains `jb inspectcode`) static analysis integration.

The runner has the ReSharper global tool installed, which reads the repository's
own `.editorconfig` and project settings. This gives deterministic, project-
specific findings (naming, style, redundancies, correctness inspections) that
are far more reliable than asking the model to guess a convention.

The flow: run `jb inspectcode` over the solution/project, parse the XML report,
and keep only issues on lines the pull request actually changed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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


def log(message: str) -> None:
    print(message, file=sys.stderr)


def find_target(workdir: str) -> Optional[str]:
    """Locate a solution/project to inspect inside ``workdir``.

    Used as a fallback when no Unity-generated solution is supplied — e.g.
    ``PeroSDK`` ships a hand-maintained ``Projects~/*.sln`` that needs no Unity
    build. Prefer that, then any ``.sln``, then any ``.csproj``. Pure UPM
    packages (only ``.asmdef``) return None here; those go through the Unity
    host-project build instead (see ``unity_runner``).
    """
    override = os.environ.get("INSPECT_TARGET", "").strip()
    if override:
        candidate = Path(workdir) / override
        return str(candidate) if candidate.exists() else override

    root = Path(workdir)
    slns = sorted(root.rglob("*.sln"))
    preferred = [s for s in slns if "Projects~" in str(s)]
    if preferred:
        return str(preferred[0])
    if slns:
        return str(slns[0])
    projects = sorted(root.rglob("*.csproj"))
    if projects:
        return str(projects[0])
    return None


def run_inspectcode(target: str, workdir: str, timeout: int = 1200) -> Optional[str]:
    """Run ``jb inspectcode`` and return the XML report path, or None on failure."""
    report = os.path.join(tempfile.gettempdir(), "resharper-report.xml")
    # Defaults honour the repo's .editorconfig and let ReSharper build as needed.
    cmd = ["jb", "inspectcode", target, f"--output={report}", "--format=Xml"]

    log(f"Running ReSharper inspectcode on {target} ...")
    try:
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        log("ReSharper 'jb' tool not found on PATH; skipping static analysis.")
        return None
    except subprocess.TimeoutExpired:
        log(f"inspectcode timed out after {timeout}s; skipping static analysis.")
        return None

    if proc.returncode != 0:
        log(f"inspectcode exited {proc.returncode}: {proc.stderr[-500:]}")
        # A report may still have been written; fall through and try to parse it.
    if not os.path.exists(report):
        log("inspectcode produced no report.")
        return None
    return report


def parse_report(report_path: str) -> List[Dict[str, Any]]:
    """Parse a ReSharper XML report into issue dicts.

    Each issue: ``{file, line, severity, message, type}`` with ``file`` relative
    to the repo root and POSIX separators.
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
            }
        )
    return issues


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


def analyze(
    workdir: str,
    changed_lines: Dict[str, Set[int]],
    sln_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Run the full ReSharper analysis and return issues on changed lines.

    ``sln_path`` is the Unity-generated solution when available; otherwise a
    target is discovered inside ``workdir`` (``Projects~`` sln, etc.).
    Never raises — static analysis is best-effort and must not break the review.
    """
    try:
        target = sln_path or find_target(workdir)
        if not target:
            log("No solution/project to inspect; skipping static analysis.")
            return []
        report = run_inspectcode(target, workdir)
        if not report:
            return []
        issues = parse_report(report)
        kept = filter_to_changes(issues, changed_lines)
        log(f"ReSharper: {len(issues)} issue(s) total, {len(kept)} on changed lines.")
        return kept
    except Exception as exc:  # noqa: BLE001 - never break the review
        log(f"Static analysis failed, continuing without it: {exc}")
        return []
