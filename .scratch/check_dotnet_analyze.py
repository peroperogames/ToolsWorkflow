"""Local check: `analyze` records how the test run ended, and says it.

Runs the real function with the two tool calls stubbed, so the bookkeeping that
turns an exit code into a sentence is exercised end to end.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import dotnet_runner


def run_case(name, build, test):
    """Analyze once with `_run` answering build, then test."""
    answers = [build, test]
    dotnet_runner.dotnet_path = lambda: "dotnet"
    dotnet_runner.solution_has_tests = lambda solution: True
    dotnet_runner._run = lambda cmd, cwd, timeout: answers.pop(0)

    work = Path(tempfile.mkdtemp(prefix="dotnet-case-"))
    (work / "src").mkdir()
    (work / "reports").mkdir()
    solution = work / "src" / "Thing.sln"
    solution.write_text("", encoding="utf-8")

    result = dotnet_runner.analyze(str(work / "src"), str(solution), work / "reports")
    print(f"--- {name}")
    print(f"    test_run: {result.test_run}")
    print(f"    zh: {result.summary()}")
    print(f"    en: {result.outcome()}")
    return result


timed_out = run_case(
    "the test run was still going at the deadline",
    (0, "Build succeeded.\n", False),
    (-1, "", True),
)
assert timed_out.tests_broke and not timed_out.tests_reported
assert timed_out.test_run["timed_out"] is True
assert "超时" in timed_out.summary() and "30 分钟" in timed_out.summary()
assert "退出码" not in timed_out.summary().split("；", 1)[1]

exited = run_case(
    "the test run exited 3 with no report",
    (0, "Build succeeded.\n", False),
    (3, "The test host crashed.\n", False),
)
assert exited.tests_broke and not exited.tests_reported
assert exited.test_run == {"exit": 3, "timed_out": False, "timeout": dotnet_runner.DOTNET_TIMEOUT}
assert "退出码 3" in exited.summary()
assert "超时" not in exited.summary()
assert "exited 3" in exited.outcome()

clean = run_case(
    "the test run exited 0 with no report",
    (0, "Build succeeded.\n", False),
    (0, "Nothing to do.\n", False),
)
assert not clean.tests_broke and clean.tested and not clean.tests_reported
assert "退出码 0" in clean.summary()
print("OK")
