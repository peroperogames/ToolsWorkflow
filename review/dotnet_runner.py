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


# Where an SDK can be besides ``PATH``. A runner can hold two: the distribution's
# one in ``/usr/bin`` and a newer one the user installed under ``~/.dotnet``, which
# is on the interactive shell's ``PATH`` but not on a job step's. PeroError PR #1
# is the case: ``net11.0`` there, ``/usr/bin/dotnet`` here, and NETSDK1045.
DOTNET_DIRS = ("~/.dotnet", "/usr/share/dotnet", "/usr/lib/dotnet")

_PICKED_DOTNET: List[Optional[str]] = []


def _version_tuple(text: str) -> Tuple[int, ...]:
    """``11.0.100`` as ``(11, 0, 100)``, ignoring any prerelease suffix."""
    first = ""
    for line in (text or "").strip().splitlines():
        if line.strip():
            first = line.strip()
            break
    parts: List[int] = []
    for piece in first.split("-")[0].split("."):
        parts.append(int(piece) if piece.isdigit() else 0)
    return tuple(parts)


def pick_newest_dotnet(
    candidates: List[str], version_of: "Any"
) -> "Tuple[Optional[str], List[Tuple[str, Tuple[int, ...]]]]":
    """The newest of ``candidates`` and every version found, for the log.

    A solution that targets a framework needs an SDK that supports it, and the one
    first on ``PATH`` is not necessarily the newest: the distribution ships one and
    the user installs another. Choosing by version, and saying which were seen,
    makes "the SDK here is too old" a fact about the runner rather than a mystery.
    """
    seen: List[Tuple[str, Tuple[int, ...]]] = []
    for candidate in candidates:
        seen.append((candidate, version_of(candidate)))
    usable = [item for item in seen if item[1]]
    if not usable:
        return (candidates[0] if candidates else None), seen
    best = max(usable, key=lambda item: item[1])
    return best[0], seen


def dotnet_path() -> Optional[str]:
    """Path to the .NET SDK CLI, or None when it is not installed.

    Reported once as a fact, like the Unity CLI and ``jb``: which one was used is
    the first thing worth knowing when a build behaves differently here than it
    does by hand. The newest SDK the runner can reach is chosen, because a job
    step's ``PATH`` is not the interactive shell's and a repository is built with
    whatever is newest rather than whatever ``/usr/bin`` happens to hold.
    """
    override = os.environ.get("DOTNET_PATH", "").strip()
    if override:
        found = shutil.which(override) or (override if os.path.exists(override) else None)
        if found:
            log(f".NET SDK: {found} (DOTNET_PATH)")
            return found
        log(f"DOTNET_PATH set but not found: {override}")
        return None

    if _PICKED_DOTNET:
        return _PICKED_DOTNET[0]

    candidates: List[str] = []
    on_path = shutil.which("dotnet")
    if on_path:
        candidates.append(on_path)
    for directory in DOTNET_DIRS:
        candidate = os.path.normpath(os.path.join(os.path.expanduser(directory), "dotnet"))
        if (
            os.path.isfile(candidate)
            and os.access(candidate, os.X_OK)
            and candidate not in candidates
        ):
            candidates.append(candidate)
    if not candidates:
        log(
            ".NET SDK ('dotnet') was not found. Checked PATH"
            + (f" and: {', '.join(DOTNET_DIRS)}." if DOTNET_DIRS else ".")
            + " Install it for the user the runner runs as. A repository that ships "
            "its own solution is not built or tested without it."
        )
        return None

    def version_of(path: str) -> Tuple[int, ...]:
        try:
            rc, text, _ = _run([path, "--version"], os.getcwd(), 60)
        except Exception:  # noqa: BLE001 - an unreadable SDK is just not a candidate
            return ()
        return _version_tuple(text) if rc == 0 else ()

    chosen, seen = pick_newest_dotnet(candidates, version_of)
    for path, version in seen:
        said = ".".join(str(p) for p in version) if version else "unknown"
        log(f".NET SDK candidate: {path} (version {said})")
    log(f".NET SDK: {chosen}")
    _PICKED_DOTNET.append(chosen)
    return chosen


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
        # How many cases the run itself said failed, across every test assembly.
        # `test_failures` is what the report spelled out by name, and a report can
        # be thinner than the run: see `parse_dotnet_test_summary`.
        self.failed_total = 0
        # One row per test assembly, as the run printed it: the only per-target
        # numbers a solution's run has, since the projects share one report file.
        self.assemblies: List[Dict[str, Any]] = []

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
            if self.tested and self.assemblies and not self._ran_any_case():
                return "⚠️ .NET: 编译通过；本次没有运行用例。" + self._assembly_table()
            return (
                "✅ .NET: 编译通过"
                + ("，单元测试通过。" if self.tested else "。")
                + self._assembly_table()
            )
        parts = []
        if not self.compiled:
            parts.append(self._compile_sentence_zh())
        if not self.tests_ok:
            # A run can fail with no case to name — a test host that exited, a
            # filter that matched nothing — and "0 个单元测试失败" is not an answer.
            parts.append(
                f"{self._failed_count()} 个单元测试失败"
                if self._failed_count()
                else f"测试运行失败（dotnet test 退出码 {self._exit_code()}）"
            )
        return "🔴 .NET: " + "；".join(parts) + "。" + self._assembly_table()

    def _assembly_table(self) -> str:
        """Per-assembly totals as a markdown table, or "" when none were printed."""
        if not self.assemblies:
            return ""
        lines = [
            "",
            "",
            "| 测试程序集 | 用例 | 通过 | 失败 | 跳过 | 耗时 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for row in self.assemblies:
            name = row.get("assembly") or "?"
            if name.endswith(".dll"):
                name = name[: -len(".dll")]
            seconds = row.get("duration")
            took = (
                f"{float(seconds):.1f}s"
                if isinstance(seconds, (int, float)) and seconds < 60
                else (f"{int(seconds) // 60}m {int(seconds) % 60}s"
                      if isinstance(seconds, (int, float)) else "—")
            )
            lines.append(
                f"| {name} | {row.get('total', 0)} | {row.get('passed', 0)} "
                f"| {row.get('failed', 0)} | {row.get('skipped', 0)} | {took} |"
            )
        return "\n".join(lines)

    def _ran_any_case(self) -> bool:
        """Whether the run actually had a case to report, per assembly."""
        return any(row.get("total") for row in self.assemblies)

    def _failed_count(self) -> int:
        """Failures to report: at least what the run printed, if more than the file."""
        return max(len(self.test_failures), self.failed_total)

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
            parts.append(
                f"{self._failed_count()} test failure(s)"
                if self._failed_count()
                else f"the test run exited {self._exit_code()}"
            )
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
        # What the run said about itself, per assembly, and what the report it
        # left behind says. A solution's projects share one report file, so the
        # report can describe only the project that finished last — the totals
        # from the output are then the only account of the others.
        summaries = build_log.parse_dotnet_test_summary(text)
        declared_failed = sum(s["failed"] for s in summaries)
        failing = [s for s in summaries if s["failed"]]
        for s in failing:
            log(
                f"  {s['assembly']}: {s['failed']} failed, {s['passed']} passed, "
                f"{s['total']} total."
            )
        if trx.exists():
            result.test_failures = build_log.parse_trx_failures(trx)
        result.tests_reported = trx.exists() or bool(summaries)
        result.failed_total = declared_failed
        result.assemblies = summaries
        if result.tests_reported:
            # The exit code is part of the answer: a run whose tests failed exits
            # non-zero even when the surviving report belongs to a project that
            # passed, which is how a solution's 9 failures went unreported.
            result.tests_ok = (
                not result.test_failures and not declared_failed and rc == 0
            )
            if not result.tests_ok:
                log(f".NET tests: {result._failed_count()} failing case(s) in {took}.")
                for line in build_log.format_test_failures(result.test_failures):
                    log(f"  {line}")
                if trx.exists():
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
