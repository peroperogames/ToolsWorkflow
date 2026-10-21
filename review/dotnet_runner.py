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
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import build_log
import repo_kind
import subproc
import tool_path

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
    """Path to the .NET SDK CLI, or None when it is not installed.

    Reported once as a fact, like the Unity CLI and ``jb``: which one was used is
    the first thing worth knowing when a build behaves differently here than it
    does by hand. Unlike those two it has no fallback directories — the SDK
    installs itself onto ``PATH``.
    """
    return tool_path.find(
        "dotnet",
        (),
        override_env="DOTNET_PATH",
        label=".NET SDK",
        hint=(
            "Install it for the user the runner runs as. A repository that ships "
            "its own solution is not built or tested without it."
        ),
    )


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


def _run(cmd: List[str], cwd: str, timeout: int) -> Tuple[int, str, bool]:
    """Run one tool and say how it ended.

    The exit code and the deadline are returned separately because they are
    different facts about a run — one exited on its own, the other was still
    running when it was stopped — and a person deciding whether to re-run the
    job needs to be told which of the two happened.
    """
    try:
        rc, text = subproc.run(cmd, timeout, cwd=cwd)
        return rc, text, False
    except subprocess.TimeoutExpired:
        log(f"{cmd[1]} timed out after {timeout}s.")
        return -1, "", True
    except OSError as exc:
        log(f"Could not run {cmd[0]}: {exc}")
        return -1, "", False


def _how_it_ended(timed_out: bool, rc: int) -> str:
    """A run's ending as a clause: a deadline or an exit code, never both."""
    if timed_out:
        return f"was still running at its {DOTNET_TIMEOUT}s deadline"
    return f"exited {rc}"


class DotnetResult:
    """Outcome of the .NET gate, shaped like ``unity_runner.UnityResult``."""

    def __init__(self) -> None:
        self.ran = False
        self.compiled = True
        self.tests_ok = True
        self.tested = False
        # The tests were started and produced nothing — the same distinction
        # `unity_runner.UnityResult` makes, for the same reason: a run that
        # produced no report must not be described as having tested anything.
        self.tests_reported = False
        # What a test run that produced no report said before giving up, and where
        # the whole of it was written — the same two facts the Unity step keeps,
        # for the same reason: "no report" is not a diagnosis.
        self.test_tail: List[str] = []
        self.test_log_path: Optional[str] = None
        # ... and did the run itself fail? A clean exit with no report is a
        # solution whose tests were not collected (the SDK decided there was
        # nothing to do); a non-zero one is the tool saying it could not run them.
        self.tests_broke = False
        # How the test run itself ended — exit code, and whether it was stopped at
        # the deadline — recorded the way `unity_runner.UnityResult.platform_failures`
        # records it. "No report" on its own cannot tell a timeout from a tool that
        # exited with an error, and those are the two things a reader asks about.
        self.test_run: Dict[str, Any] = {}
        # ... and the build's own deadline, which has no error list to report.
        self.build_timed_out = False
        self.compile_errors: List[Dict[str, Any]] = []
        self.test_failures: List[Dict[str, Any]] = []

    @property
    def ok(self) -> bool:
        return self.compiled and self.tests_ok

    def summary(self) -> str:
        """One line about this step, for the pull request.

        The bot speaks the review's language on the pull request; :meth:`outcome`
        is the same thing for the job log, which is English throughout.
        """
        if not self.ran:
            return ""
        if self.ok:
            if self.tests_broke:
                return f"⚠️ .NET: 编译通过；{self._failure_sentence_zh()}，没有产出报告。"
            if self.tested and not self.tests_reported:
                return (
                    "⚠️ .NET: 编译通过；单元测试没有产出报告"
                    f"（dotnet test 退出码 {self._exit_code()}），本次未真正运行。"
                )
            return "✅ .NET: 编译通过" + ("，单元测试通过。" if self.tested else "。")
        parts = []
        if not self.compiled:
            parts.append(self._compile_sentence_zh())
        if not self.tests_ok:
            parts.append(f"{len(self.test_failures)} 个单元测试失败")
        return "🔴 .NET: " + "；".join(parts) + "。"

    def _exit_code(self) -> Any:
        """The test run's exit code, or ``"未知"`` if the run has no record."""
        code = self.test_run.get("exit")
        return "未知" if code is None else code

    def _compile_sentence_zh(self) -> str:
        """Why the build is not a passing one, in the review's language.

        A build stopped at the deadline has no error list to count: it failed to
        finish, which is what the sentence has to say rather than "0 个错误".
        """
        if self.build_timed_out:
            return "编译超时"
        return f"编译失败（{len(self.compile_errors)} 个错误）"

    def _failure_sentence_zh(self) -> str:
        """How the test run ended, in the review's language.

        Its own sentence rather than "测试没有跑完", which does not say whether the
        run is still going, was killed at a deadline, or exited on its own — and a
        reader deciding whether to wait or to re-run needs exactly that.
        """
        if self.test_run.get("timed_out"):
            return f".NET 测试超时（{self._timeout_limit()}还没跑完，被停掉了）"
        return f".NET 测试运行失败（dotnet test 退出码 {self._exit_code()}）"

    def _failure_sentence_en(self) -> str:
        """The same sentence for the job log, which is written in English."""
        if self.test_run.get("timed_out"):
            return (
                f"the test run was still running after {self._timeout_limit_en()} "
                "and was stopped"
            )
        return f"the test run exited {self.test_run.get('exit', 'with an unknown status')}"

    def _timeout_limit(self) -> str:
        """The test deadline as a person would say it."""
        seconds = int(self.test_run.get("timeout") or DOTNET_TIMEOUT)
        minutes = seconds // 60
        return f"{minutes} 分钟" if minutes else f"{seconds} 秒"

    def _timeout_limit_en(self) -> str:
        seconds = int(self.test_run.get("timeout") or DOTNET_TIMEOUT)
        minutes = seconds // 60
        return f"{minutes} minutes" if minutes else f"{seconds} seconds"

    def outcome(self) -> str:
        """The same result for the job log. Empty when the step did not run."""
        if not self.ran:
            return ""
        if self.ok:
            if self.tests_broke:
                return f".NET: built; {self._failure_sentence_en()}, so it produced no report."
            if self.tested and not self.tests_reported:
                return (
                    ".NET: built; the test run produced no report "
                    f"(dotnet test exited {self._exit_code()})."
                )
            return ".NET: built" + (" and tested." if self.tested else ".")
        parts = []
        if not self.compiled:
            if self.build_timed_out:
                parts.append(
                    f"the build was still running after {DOTNET_TIMEOUT // 60} minutes "
                    "and was stopped"
                )
            else:
                parts.append(f"{len(self.compile_errors)} compile error(s)")
        if not self.tests_ok:
            parts.append(f"{len(self.test_failures)} test failure(s)")
        return ".NET: " + ", ".join(parts) + "."


def _save_output(path: Path, output: str, limit: int = 2_000_000) -> bool:
    """Write what a run printed to ``path``, keeping the end of it. Best-effort."""
    if not output.strip():
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output[-limit:], encoding="utf-8", errors="replace")
    except OSError as exc:
        log(f"Could not write {path}: {exc}")
        return False
    return True


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
        started = time.monotonic()
        rc, text, timed_out = _run(
            [dotnet, "build", solution, "--nologo", "-v", "minimal"],
            clone_dir,
            DOTNET_TIMEOUT,
        )
        took = build_log.format_duration(time.monotonic() - started)
        errors = build_log.parse_compile_errors(text)
        if errors:
            log(f".NET build failed in {took}: {len(errors)} error(s).")
            for line in build_log.format_compile_errors(errors):
                log(f"  {line}")
            result.ran = True
            result.compiled = False
            result.compile_errors = errors
            # No point testing code that does not compile.
            return result
        if rc != 0:
            # A failure we could not attribute to a source line or an error code
            # is a toolchain problem, not a verdict on the pull request.
            if timed_out:
                result.build_timed_out = True
                log(
                    f"dotnet build was still running after {DOTNET_TIMEOUT}s and was "
                    "stopped; skipping the step."
                )
            else:
                log(f"dotnet build exited {rc} after {took} with no parseable error; skipping the step.")
            said = " ".join(text.split())[-800:]
            if said:
                log(f"dotnet said: {said}")
            return result

        result.ran = True
        result.compiled = True
        log(f".NET: compiled in {took}.")

        if not solution_has_tests(solution):
            log(".NET: no test project in the solution; build only.")
            return result

        log(f".NET: testing {Path(solution).name} ...")
        trx = report_dir / "dotnet-test.trx"
        trx.parent.mkdir(parents=True, exist_ok=True)
        if trx.exists():
            trx.unlink()
        started = time.monotonic()
        rc, text, timed_out = _run(
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
        took = build_log.format_duration(time.monotonic() - started)
        result.tested = True
        result.test_run = {"exit": rc, "timed_out": timed_out, "timeout": DOTNET_TIMEOUT}
        if trx.exists():
            result.test_failures = build_log.parse_trx_failures(trx)
            result.tests_ok = not result.test_failures
            result.tests_reported = True
            if result.test_failures:
                log(f".NET tests: {len(result.test_failures)} failing case(s) in {took}.")
                for line in build_log.format_test_failures(result.test_failures):
                    log(f"  {line}")
                log(f"  report: {trx}")
            else:
                log(f".NET tests finished in {took} with no failing case.")
        else:
            # No report means the SDK could not run the tests at all — that is
            # not evidence of a failing test, so it must not fail the build, and
            # it is not evidence of a passing one either.
            log(
                f"dotnet test produced no report after {took} "
                f"({_how_it_ended(timed_out, rc)}); not counting it as a failure, and "
                "not reporting the run as tested either."
            )
            said = " ".join(text.split())[-800:]
            if said:
                log(f"dotnet said: {said}")
            result.test_tail = build_log.tail_lines(text)
            log_path = report_dir / "dotnet-test.log"
            if _save_output(log_path, text):
                result.test_log_path = str(log_path)
                log(f"  full output: {log_path}")
            if rc != 0:
                result.tests_broke = True
        return result
    except Exception as exc:  # noqa: BLE001 - never break the review
        log(f".NET step failed, continuing without it: {exc}")
        return result
