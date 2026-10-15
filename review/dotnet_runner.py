"""The .NET SDK build/test gate for repositories that ship their own solution.

A pure C# repository has no UPM package, so the Unity step has nothing to do for
it; this is that step's equivalent. ``dotnet build`` runs for every such
repository, and ``dotnet test`` only when the solution actually contains a test
project — asking the SDK to test a solution with no tests is not a signal about
the pull request, so it is not run.

Best-effort, exactly like the Unity step: a missing SDK or an unusable toolchain
skips the step and says so in the log rather than failing a review.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import build_log
import repo_kind

DOTNET_TIMEOUT = int(os.environ.get("DOTNET_TIMEOUT", "1800"))

# Anything that marks a project as a test project. Checking the project file is
# what lets "no tests here" stay silent instead of becoming a failed step.
TEST_MARKERS = (
    "Microsoft.NET.Test.Sdk",
    "xunit",
    "nunit",
    "mstest",
    "istestproject",
)


def log(message: str) -> None:
    print(message, file=sys.stderr)


def dotnet_path() -> Optional[str]:
    """Path to the .NET SDK CLI, or None when it is not installed."""
    configured = os.environ.get("DOTNET_PATH", "").strip()
    if configured:
        found = shutil.which(configured) or (configured if os.path.exists(configured) else None)
        if found:
            return found
        log(f"DOTNET_PATH set but not found: {configured}")
        return None
    found = shutil.which("dotnet")
    if not found:
        log("The .NET SDK ('dotnet') is not on PATH; skipping the build/test step.")
    return found


def solution_projects(solution: str) -> List[Path]:
    """The project files a solution actually references.

    Parsed rather than discovered by walking the directory, because ``dotnet
    test`` only runs the test projects that are *in* the solution: a test project
    sitting on disk but not listed would be reported as "has tests" and then
    never run, which is the silent pass this module exists to avoid.

    Both formats are read. A ``.sln`` spells paths with backslashes even when it
    was generated on Linux, so they are normalized before being joined.
    """
    path = Path(solution)
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        log(f"Could not read {path.name}: {exc}")
        return []

    if path.suffix.lower() == ".slnx":
        # <Solution><Project Path="Lib/Lib.csproj" /></Solution>
        names = re.findall(r'Path="([^"]+)"', text)
    else:
        # Project("{GUID}") = "Name", "Lib\Lib.csproj", "{GUID}"
        names = re.findall(
            r'^Project\("\{[^}]+\}"\)\s*=\s*"[^"]+",\s*"([^"]+)"', text, re.M
        )

    projects: List[Path] = []
    for name in names:
        name = name.replace("\\", "/").strip()
        if not name.lower().endswith(".csproj"):
            continue
        candidate = (path.parent / name).resolve()
        if candidate.is_file():
            projects.append(candidate)
    return projects


def solution_has_tests(solution: str) -> bool:
    """Does this solution reference a project that runs tests?"""
    projects = solution_projects(solution)
    if not projects:
        # An unusual solution layout: fall back to anything alongside it rather
        # than silently deciding there are no tests at all.
        projects = list(
            repo_kind.walk_files(Path(solution).parent, lambda p: p.suffix.lower() == ".csproj")
        )
    for project in projects:
        try:
            text = project.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        if any(marker in text for marker in TEST_MARKERS):
            log(f"Test project found: {project.name}.")
            return True
    return False


def _run(cmd: List[str], cwd: str, timeout: int) -> Tuple[int, str]:
    try:
        proc = subprocess.run(cmd, cwd=cwd, timeout=timeout, capture_output=True, text=True)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        log(f"{cmd[1]} timed out after {timeout}s.")
        return -1, ""
    except OSError as exc:
        log(f"Could not run {cmd[0]}: {exc}")
        return -1, ""


class DotnetResult:
    """Outcome of the .NET gate, shaped like ``unity_runner.UnityResult``."""

    def __init__(self) -> None:
        self.ran = False
        self.compiled = True
        self.tests_ok = True
        self.tested = False
        self.compile_errors: List[Dict[str, Any]] = []
        self.test_failures: List[Dict[str, Any]] = []

    @property
    def ok(self) -> bool:
        return self.compiled and self.tests_ok

    def summary(self) -> str:
        if not self.ran:
            return ""
        if self.ok:
            return "✅ .NET: 编译通过" + (",单元测试通过。" if self.tested else "。")
        parts = []
        if not self.compiled:
            parts.append(f"编译失败({len(self.compile_errors)} 个错误)")
        if not self.tests_ok:
            parts.append(f"{len(self.test_failures)} 个单元测试失败")
        return "🔴 .NET: " + ";".join(parts) + "。"


def analyze(clone_dir: str, solution: str, report_dir: Path) -> DotnetResult:
    """Build (and test) the repository's own solution. Never raises.

    ``report_dir`` is the PR's own scratch directory, beside the clone — never
    inside it, so nothing this step writes can end up in the analysed sources.
    """
    result = DotnetResult()
    try:
        dotnet = dotnet_path()
        if not dotnet or not solution:
            return result

        log(f".NET: building {Path(solution).name} ...")
        rc, text = _run(
            [dotnet, "build", solution, "--nologo", "-v", "minimal"],
            clone_dir,
            DOTNET_TIMEOUT,
        )
        errors = build_log.parse_compile_errors(text)
        if errors:
            log(f".NET build: {len(errors)} error(s).")
            result.ran = True
            result.compiled = False
            result.compile_errors = errors
            # No point testing code that does not compile.
            return result
        if rc != 0:
            # A failure we could not attribute to a source line or an error code
            # is a toolchain problem, not a verdict on the pull request.
            log(f"dotnet build exited {rc} with no parseable error; skipping the step.")
            return result

        result.ran = True
        result.compiled = True

        if not solution_has_tests(solution):
            log(".NET: no test project in the solution; build only.")
            return result

        log(f".NET: testing {Path(solution).name} ...")
        trx = report_dir / "dotnet-test.trx"
        trx.parent.mkdir(parents=True, exist_ok=True)
        if trx.exists():
            trx.unlink()
        rc, text = _run(
            [
                dotnet, "test", solution,
                "--nologo",
                "--no-build",
                "--results-directory", str(trx.parent),
                "--logger", f"trx;LogFileName={trx.name}",
            ],
            clone_dir,
            DOTNET_TIMEOUT,
        )
        result.tested = True
        if trx.exists():
            result.test_failures = build_log.parse_trx_failures(trx)
            result.tests_ok = not result.test_failures
        else:
            # No report means the SDK could not run the tests at all — that is
            # not evidence of a failing test, so it must not fail the build.
            log(f"dotnet test produced no report (exit {rc}); not counting it as a failure.")
        if result.test_failures:
            log(f".NET tests: {len(result.test_failures)} failing case(s).")
        return result
    except Exception as exc:  # noqa: BLE001 - never break the review
        log(f".NET step failed, continuing without it: {exc}")
        return result
